"""
Kronos web app -- a browser front end over everything built in assistant/
and backtesting/. No business logic lives here: every route is a thin
wrapper that calls into StockAssistant, assistant.data_fetcher,
assistant.forecaster, assistant.charts, assistant.watchlist, or
backtesting.runner.quick_backtest, exactly like chat_cli.py and the
Discord/WhatsApp adapters do.

Run with:
    python webapp/app.py
Then open http://127.0.0.1:5050
"""
import os
import sys
import threading
import time
import uuid
from datetime import timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    jsonify, flash, send_from_directory, abort, Response,
)

from assistant.core_assistant import StockAssistant
from assistant import watchlist as watchlist_store
from assistant import data_fetcher, indicators, forecaster as forecaster_mod, charts, config as assistant_config
from assistant import portfolio_analysis, fundamentals, watchlist_extras
from assistant import news as news_mod, llm as llm_mod
from assistant import storage as storage_mod
from assistant.screener import engine as screener_engine
from assistant.screener import universe as screener_universe
from assistant.screener import presets as screener_presets
from assistant.screener import filters as screener_filters
from assistant.screener import history as screener_history
from assistant import simulation as simulation_store
from assistant.config import SCREENER_CONFIG
from assistant.data_fetcher import TickerNotFoundError
from assistant.ticker_directory import search_tickers
from assistant.conversation import get_context
from backtesting.data_loaders import CSVLoader
from jobs import JobManager

app = Flask(__name__)
app.secret_key = os.getenv("WEBAPP_SECRET_KEY", "kronos-dev-secret-change-me")

# Without this, Flask's session cookie has no expiry and the browser
# drops it as soon as it's closed -- so _user_id() (below) would hand out
# a brand-new anonymous identity on your next visit, and everything tied
# to it (watchlist, screener history, and especially an open demo
# position you "let sit there" for days -- see assistant/simulation.py)
# would look like it never saved, even though it's still sitting in
# assistant_data/ under the old, now-unreachable id. Making the session
# permanent with a long lifetime turns the cookie into a stable identity
# across visits, which is what every one of those per-user JSON stores
# was already assuming.
app.permanent_session_lifetime = timedelta(days=365)


@app.before_request
def _make_session_permanent():
    session.permanent = True


bot = StockAssistant()

# ---------------------------------------------------------------------------
# Background chat jobs
# ---------------------------------------------------------------------------
# A chat reply (a real Kronos forecast run, in particular) can take a while.
# Rather than tying that work to the lifetime of one HTTP request -- which
# dies the moment the browser navigates to another page/tab -- a message is
# handed to a background thread immediately, and the browser polls for the
# result. That means the reply keeps computing (and lands in the persisted
# conversation history) even if the person leaves the Chat page entirely;
# returning to /chat later picks the same job back up via /api/chat/pending.
#
# In-memory only (fine for a single-process local app -- restarting the
# server drops any job still in flight, same as any other in-memory state
# here). Requires the dev server to run with threaded=True (see bottom of
# this file) so a poll request isn't blocked behind the worker thread.
_chat_jobs = {}       # job_id -> {"user_id", "status", "message", "result"|"error", "created"}
_pending_by_user = {}  # user_id -> job_id, cleared once the job is delivered
_jobs_lock = threading.Lock()
_JOB_TTL_SECONDS = 30 * 60  # done/error jobs older than this are swept on next start


def _sweep_old_jobs():
    cutoff = time.time() - _JOB_TTL_SECONDS
    stale = [jid for jid, j in _chat_jobs.items() if j["status"] != "pending" and j["created"] < cutoff]
    for jid in stale:
        _chat_jobs.pop(jid, None)


def _run_chat_job(job_id, user_id, text):
    try:
        result = bot.handle_message(user_id, text)
        with _jobs_lock:
            job = _chat_jobs.get(job_id)
            if job is not None:
                job["status"] = "done"
                job["result"] = result
    except Exception as e:  # keep the worker thread from dying silently
        with _jobs_lock:
            job = _chat_jobs.get(job_id)
            if job is not None:
                job["status"] = "error"
                job["error"] = str(e)
    finally:
        with _jobs_lock:
            if _pending_by_user.get(user_id) == job_id:
                del _pending_by_user[user_id]


# ---------------------------------------------------------------------------
# Background forecast jobs (the manual "/forecast" page's ticker + CSV
# forms). This used to be a plain synchronous POST -- the request (and the
# one worker thread handling it) sat blocked for the entire Kronos
# inference time, and a slow/CPU-only forecast looked identical to a hung
# server. It now follows exactly the same background-thread-plus-polling
# pattern already used for chat above, so the page can show real progress
# instead of a spinner glued to a frozen request.
# ---------------------------------------------------------------------------
_forecast_jobs = {}
_forecast_jobs_lock = threading.Lock()


def _sweep_old_forecast_jobs():
    cutoff = time.time() - _JOB_TTL_SECONDS
    stale = [jid for jid, j in _forecast_jobs.items() if j["status"] != "pending" and j["created"] < cutoff]
    for jid in stale:
        _forecast_jobs.pop(jid, None)


def _finish_forecast_job(job_id, *, status, result=None, error=None):
    with _forecast_jobs_lock:
        job = _forecast_jobs.get(job_id)
        if job is not None:
            job["status"] = status
            if result is not None:
                job["result"] = result
            if error is not None:
                job["error"] = error


def _run_forecast_ticker_job(job_id, ticker, pred_len, lookback, detailed):
    try:
        hist_df = data_fetcher.fetch_history(ticker, lookback_days=lookback)
        if detailed:
            from assistant.config import DETAILED_FORECAST_RUNS
            fc = forecaster_mod.run_forecast(hist_df, pred_len=pred_len, n_runs=DETAILED_FORECAST_RUNS)
            image_path = charts.build_detailed_forecast_png(ticker, hist_df, fc)
        else:
            fc = forecaster_mod.run_forecast(hist_df, pred_len=pred_len)
            image_path = charts.build_forecast_png(ticker, hist_df, fc)

        last_close = float(hist_df["close"].iloc[-1])
        if detailed and fc.get("mean_df") is not None:
            forecast_close = float(fc["mean_df"]["close"].iloc[-1])
        else:
            forecast_close = float(fc["pred_df"]["close"].iloc[-1])
        pct = (forecast_close - last_close) / last_close * 100
        result_text = (
            f"{ticker}: {last_close:.2f} -> {forecast_close:.2f} over {pred_len} trading days "
            f"({pct:+.2f}%). Lookback used: {fc['lookback_used']} days."
        )
        if detailed:
            result_text += f" ({fc['n_runs']} sampled paths shown.)"
        _finish_forecast_job(job_id, status="done", result={
            "text": result_text, "ticker": ticker, "image_path": image_path,
        })
    except TickerNotFoundError as e:
        _finish_forecast_job(job_id, status="error", error=str(e))
    except Exception as e:
        _finish_forecast_job(job_id, status="error", error=f"Forecast failed: {e}")


def _run_forecast_csv_job(job_id, file_bytes, label, pred_len):
    try:
        import io
        import pandas as pd
        raw_df = pd.read_csv(io.BytesIO(file_bytes))
        hist_df = CSVLoader().normalize(raw_df)
        if len(hist_df) < 30:
            raise ValueError("Need at least 30 rows of history to forecast anything useful.")

        fc = forecaster_mod.run_forecast(hist_df, pred_len=pred_len)
        image_path = charts.build_forecast_png(label, hist_df, fc)

        last_close = float(hist_df["close"].iloc[-1])
        forecast_close = float(fc["pred_df"]["close"].iloc[-1])
        pct = (forecast_close - last_close) / last_close * 100
        result_text = (
            f"{label}: {last_close:.2f} -> {forecast_close:.2f} over {pred_len} trading days "
            f"({pct:+.2f}%). Rows read from CSV: {len(hist_df)}, lookback used: {fc['lookback_used']} days."
        )
        _finish_forecast_job(job_id, status="done", result={
            "text": result_text, "ticker": label, "image_path": image_path,
        })
    except Exception as e:
        _finish_forecast_job(job_id, status="error", error=f"Couldn't process that CSV: {e}")


@app.context_processor
def inject_integration_status():
    """Makes an `integrations` dict available in every template (sidebar
    badges, etc.) without every route having to pass it explicitly. Reflects
    the *actual* runtime state -- e.g. ai_wording_enabled only reports True
    if the Anthropic client really initialized, not just if a key is set."""
    return {
        "integrations": {
            "news_extra_configured": bool(assistant_config.FINNHUB_API_KEY or assistant_config.NEWSAPI_API_KEY),
            "news_source_label": news_mod.active_source(),
            "ai_wording_enabled": llm_mod.is_available(),
        }
    }

# Charts/backtest images already save under assistant_data/{charts,backtests};
# this route serves them directly instead of copying into static/.
SERVABLE_ROOTS = {
    "charts": assistant_config.CHARTS_DIR,
    "backtests": assistant_config.BACKTEST_DIR,
}


def _user_id():
    if "user_id" not in session:
        session["user_id"] = f"web-{uuid.uuid4().hex[:12]}"
    return session["user_id"]


def _to_url(path):
    """Turn an absolute file path under one of SERVABLE_ROOTS into a /media/ URL."""
    if not path:
        return None
    for key, root in SERVABLE_ROOTS.items():
        root_abs = os.path.abspath(root)
        path_abs = os.path.abspath(path)
        if path_abs.startswith(root_abs):
            rel = os.path.relpath(path_abs, root_abs)
            return url_for("media", root=key, filename=rel.replace(os.sep, "/"))
    return None


@app.route("/media/<root>/<path:filename>")
def media(root, filename):
    base = SERVABLE_ROOTS.get(root)
    if base is None:
        abort(404)
    return send_from_directory(base, filename)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    wl = watchlist_store.get(_user_id())
    return render_template("index.html", active="home", watchlist=wl,
                            kronos_model_id=assistant_config.KRONOS_MODEL_ID)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
@app.route("/chat")
def chat():
    return render_template("chat.html", active="chat")


@app.route("/api/chat/history")
def api_chat_history():
    context = get_context(_user_id())
    return jsonify({"history": context.history, "beginner_mode": context.beginner_mode})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Synchronous path -- kept for the mode-toggle switch (instant, no
    Kronos call involved). Actual chat messages go through
    /api/chat/send + /api/chat/job/<id> instead (see below) so a slow
    reply survives the user navigating to another page."""
    payload = request.get_json(silent=True) or {}
    text = (payload.get("message") or "").strip()

    if not text and payload.get("mode") in ("beginner", "advanced"):
        text = f"use {payload['mode']} mode"

    if not text:
        return jsonify({"text": "Say something and I'll take a look."})

    result = bot.handle_message(_user_id(), text)
    return jsonify({
        "text": result.get("text", ""),
        "image_url": _to_url(result.get("image_path")),
        "suggestions": result.get("suggestions", []),
        "sparkline": (result.get("data") or {}).get("sparkline", []),
    })


@app.route("/api/chat/send", methods=["POST"])
def api_chat_send():
    """Kicks off a chat reply in a background thread and returns
    immediately with a job id -- the actual work (and its eventual
    result) lives independently of this request, so it isn't cancelled
    by the browser navigating away. Poll /api/chat/job/<job_id> for the
    result."""
    payload = request.get_json(silent=True) or {}
    text = (payload.get("message") or "").strip()
    if not text:
        return jsonify({"error": "empty message"}), 400

    user_id = _user_id()
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _sweep_old_jobs()
        _chat_jobs[job_id] = {
            "user_id": user_id, "status": "pending",
            "message": text, "created": time.time(),
        }
        _pending_by_user[user_id] = job_id

    threading.Thread(target=_run_chat_job, args=(job_id, user_id, text), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/chat/job/<job_id>")
def api_chat_job(job_id):
    with _jobs_lock:
        job = _chat_jobs.get(job_id)
        if job is None:
            return jsonify({"status": "not_found"}), 404
        if job["user_id"] != _user_id():
            abort(403)
        status = job["status"]
        result = job.get("result")

    if status == "pending":
        return jsonify({"status": "pending"})
    if status == "error":
        return jsonify({"status": "error", "text": "⚠️ Something went wrong on the last message."})

    # "done" -- convert the file path to a servable URL here (needs an
    # active request context, unlike the background thread it was
    # computed in).
    return jsonify({
        "status": "done",
        "text": result.get("text", ""),
        "image_url": _to_url(result.get("image_path")),
        "suggestions": result.get("suggestions", []),
        "sparkline": (result.get("data") or {}).get("sparkline", []),
    })


@app.route("/api/chat/pending")
def api_chat_pending():
    """Checked when the Chat page loads -- if the user sent a message,
    switched tabs, and came back before it finished, this lets the page
    re-show the pending user bubble + typing indicator and resume
    polling, instead of the reply silently landing while no one's
    watching."""
    with _jobs_lock:
        job_id = _pending_by_user.get(_user_id())
        message = _chat_jobs.get(job_id, {}).get("message") if job_id else None
    return jsonify({"job_id": job_id, "message": message})


@app.route("/api/tickers/search")
def api_ticker_search():
    q = request.args.get("q", "")
    results = search_tickers(q)
    return jsonify({"results": [{"symbol": s, "name": n} for s, n in results]})


# ---------------------------------------------------------------------------
# News -- ticker-specific headlines + sentiment (assistant/news.py)
# ---------------------------------------------------------------------------
@app.route("/news")
def news():
    ticker = (request.args.get("ticker") or "").strip().upper()
    return render_template("news.html", active="news", ticker=ticker)


@app.route("/api/news")
def api_news():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "Enter a ticker."}), 400
    try:
        items, summary = news_mod.get_news(ticker, limit=12)
    except Exception:
        return jsonify({"error": f"Couldn't fetch news for {ticker} right now."}), 502
    return jsonify({
        "ticker": ticker,
        "items": items,
        "summary": summary,
        "source_label": news_mod.active_source(),
    })


# ---------------------------------------------------------------------------
# Ticker price chart -- Google-Finance-style popup used from Watchlist,
# Screener, and Simulation (see static/js/ticker-chart.js). Deliberately
# reuses data_fetcher.fetch_history() exactly as every other page already
# does -- same provider, same cache, same "1d" interval -- rather than
# adding a new data path. Ranges are expressed as a daily-bar lookback
# count (not calendar days) since that's what fetch_history expects.
# ---------------------------------------------------------------------------
CHART_RANGE_LOOKBACK = {
    "1M": 25, "3M": 68, "6M": 135, "YTD": 400, "1Y": 260, "5Y": 1300, "MAX": 7500,
}


@app.route("/api/chart/<ticker>")
def api_chart(ticker):
    ticker = (ticker or "").strip().upper()
    range_key = (request.args.get("range") or "6M").upper()
    lookback = CHART_RANGE_LOOKBACK.get(range_key, CHART_RANGE_LOOKBACK["6M"])

    try:
        df = data_fetcher.fetch_history(ticker, lookback_days=lookback, interval="1d")
    except TickerNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception:
        return jsonify({"error": f"Couldn't fetch chart data for {ticker} right now."}), 502

    if range_key == "YTD":
        import pandas as pd
        this_year = pd.Timestamp.now().year
        ytd_df = df[df["timestamps"].dt.year == this_year]
        # Very early January: not enough YTD rows yet -- fall back to a
        # short recent window rather than showing an empty chart.
        df = ytd_df if len(ytd_df) >= 2 else df.tail(10)

    if df is None or df.empty:
        return jsonify({"error": f"No chart data available for {ticker}."}), 404

    points = [
        {"t": ts.strftime("%Y-%m-%d"), "c": round(float(close), 4)}
        for ts, close in zip(df["timestamps"], df["close"])
    ]
    latest = float(df["close"].iloc[-1])
    first = float(df["close"].iloc[0])
    prev = float(df["close"].iloc[-2]) if len(df) > 1 else latest

    return jsonify({
        "ticker": ticker,
        "range": range_key,
        "points": points,
        "latest_price": round(latest, 2),
        "day_change": round(latest - prev, 2),
        "day_change_pct": round((latest - prev) / prev * 100, 2) if prev else 0.0,
        "range_change": round(latest - first, 2),
        "range_change_pct": round((latest - first) / first * 100, 2) if first else 0.0,
    })


# ---------------------------------------------------------------------------
# Stock Screener (assistant/screener/)
# ---------------------------------------------------------------------------
@app.route("/screener", methods=["GET"])
def screener():
    return render_template(
        "screener.html", active="screener",
        universes=screener_universe.UNIVERSES, presets=screener_presets.PRESETS,
        metric_catalog=screener_filters.METRIC_CATALOG, config=SCREENER_CONFIG,
        run_history=screener_history.get_history(_user_id(), limit=20),
    )


_screener_jobs = JobManager()


def _run_screener_job(user_id, universe_key, preset_key, custom_text, csv_rows, custom_filters,
                       min_dollar_volume, lookback_days, preselection_count, final_count,
                       enable_kronos, pred_len):
    result = screener_engine.run_screen(
        universe_key=universe_key, user_id=user_id,
        custom_text=custom_text, csv_rows=csv_rows,
        preset_key=preset_key, custom_filters=custom_filters,
        min_avg_dollar_volume=min_dollar_volume, lookback_days=lookback_days,
        preselection_count=preselection_count, final_count=final_count,
        enable_kronos=enable_kronos, pred_len=pred_len,
    )
    if result.get("error"):
        raise RuntimeError(result["error"])
    # Record which tickers this screen returned -- only for a real,
    # completed result, so history reflects actual scans a user would
    # want to look back at. Done here (in the background job) rather than
    # in the route, since by the time the route gets a response back this
    # already happened.
    screener_history.record_run(user_id, result, universe_key, preset_key)
    return {"result": result, "universe_key": universe_key, "preset_key": preset_key}


@app.route("/screener/run", methods=["POST"])
def screener_run():
    """
    Scanning a universe with Kronos enabled means one forecast call per
    ticker that survives to the final stage (see SCREENER_CONFIG's
    final_count) -- by far the slowest single form submission in this
    app before this was made async. Parses the request here (form data
    and an uploaded CSV file don't survive into a background thread) then
    hands the actual scan off to a background job; see
    /screener/job/<id> to poll and /screener/result/<id> to render the
    finished page once done.
    """
    universe_key = request.form.get("universe") or "sp500"
    preset_key = request.form.get("preset") or "none"
    custom_text = request.form.get("custom_tickers") or ""
    enable_kronos = request.form.get("enable_kronos") == "on"
    pred_len = int(request.form.get("pred_len") or 30)
    min_dollar_volume = float(request.form.get("min_dollar_volume") or SCREENER_CONFIG["min_avg_dollar_volume"])
    lookback_days = int(request.form.get("lookback_days") or SCREENER_CONFIG["lookback_days"])
    preselection_count = int(request.form.get("preselection_count") or SCREENER_CONFIG["preselection_count"])
    final_count = int(request.form.get("final_count") or SCREENER_CONFIG["final_count"])

    csv_rows = None
    if universe_key == "csv":
        file = request.files.get("csv_file")
        if not file or file.filename == "":
            return jsonify({"error": "Choose a CSV file with a ticker/symbol column first."}), 400
        import csv
        import io
        try:
            text = file.read().decode("utf-8-sig")
            csv_rows = list(csv.DictReader(io.StringIO(text)))
        except Exception as e:
            return jsonify({"error": f"Couldn't read that CSV: {e}"}), 400

    custom_filters = []
    raw_filters = request.form.get("custom_filters_json") or "[]"
    try:
        import json
        for f in json.loads(raw_filters):
            metric, op, val = f.get("metric"), f.get("op"), f.get("value")
            if not metric or not op or val in (None, ""):
                continue
            val = float(val)
            if metric in screener_filters.PERCENT_METRICS:
                val = val / 100.0
            custom_filters.append((metric, op, val))
    except (ValueError, TypeError, AttributeError):
        pass  # malformed filter rows are skipped, not a hard error -- the rest of the screen still runs

    job_id = _screener_jobs.submit(
        _run_screener_job, _user_id(), universe_key, preset_key, custom_text, csv_rows,
        custom_filters, min_dollar_volume, lookback_days, preselection_count, final_count,
        enable_kronos, pred_len,
    )
    return jsonify({"job_id": job_id})


@app.route("/screener/job/<job_id>")
def screener_job(job_id):
    return jsonify(_screener_jobs.poll(job_id))


@app.route("/screener/result/<job_id>")
def screener_result(job_id):
    payload = _screener_jobs.get_result(job_id)
    if payload is None:
        flash("That screen result has expired or wasn't found -- please run it again.", "error")
        return redirect(url_for("screener"))
    return render_template(
        "screener.html", active="screener",
        universes=screener_universe.UNIVERSES, presets=screener_presets.PRESETS,
        metric_catalog=screener_filters.METRIC_CATALOG, config=SCREENER_CONFIG,
        result=payload["result"], run_history=screener_history.get_history(_user_id(), limit=20),
    )


@app.route("/screener/history/clear", methods=["POST"])
def screener_history_clear():
    screener_history.clear_history(_user_id())
    flash("Screen history cleared.", "ok")
    return redirect(url_for("screener"))


# ---------------------------------------------------------------------------
# Forecast -- ticker and CSV upload
# ---------------------------------------------------------------------------
@app.route("/forecast")
def forecast():
    return render_template("forecast.html", active="forecast", prefill_ticker=request.args.get("ticker", ""))


@app.route("/forecast/ticker", methods=["POST"])
def forecast_ticker():
    """
    Kicks off a ticker forecast in a background thread and returns
    immediately with a job id (JSON) instead of blocking this request for
    the full Kronos inference time -- see forecast.js for the polling
    loop against /forecast/job/<id>. Mirrors /api/chat/send's pattern.
    """
    ticker = (request.form.get("ticker") or "").strip().upper()
    pred_len = int(request.form.get("pred_len") or 30)
    lookback = int(request.form.get("lookback") or 400)
    detailed = request.form.get("detailed") == "on"

    if not ticker:
        return jsonify({"error": "Enter a ticker first."}), 400

    job_id = uuid.uuid4().hex
    with _forecast_jobs_lock:
        _sweep_old_forecast_jobs()
        _forecast_jobs[job_id] = {"status": "pending", "created": time.time()}
    threading.Thread(
        target=_run_forecast_ticker_job,
        args=(job_id, ticker, pred_len, lookback, detailed),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.route("/forecast/csv", methods=["POST"])
def forecast_csv():
    """Same background-job treatment as forecast_ticker, for CSV uploads."""
    file = request.files.get("file")
    label = (request.form.get("name") or "UPLOAD").strip().upper() or "UPLOAD"
    pred_len = int(request.form.get("pred_len") or 30)

    if not file or file.filename == "":
        return jsonify({"error": "Choose a CSV file first."}), 400

    file_bytes = file.read()  # must read now -- the file handle won't survive past this request

    job_id = uuid.uuid4().hex
    with _forecast_jobs_lock:
        _sweep_old_forecast_jobs()
        _forecast_jobs[job_id] = {"status": "pending", "created": time.time()}
    threading.Thread(
        target=_run_forecast_csv_job,
        args=(job_id, file_bytes, label, pred_len),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.route("/forecast/job/<job_id>")
def forecast_job(job_id):
    with _forecast_jobs_lock:
        job = _forecast_jobs.get(job_id)
        if job is None:
            return jsonify({"status": "not_found"}), 404
        status = job["status"]
        result = job.get("result")
        error = job.get("error")

    if status == "pending":
        return jsonify({"status": "pending"})
    if status == "error":
        return jsonify({"status": "error", "message": error or "Something went wrong."})

    # "done" -- convert the file path to a servable URL here (needs an
    # active request context, unlike the background thread it was
    # computed in -- same reasoning as /api/chat/job/<id> above).
    return jsonify({
        "status": "done",
        "text": result["text"],
        "ticker": result["ticker"],
        "image_url": _to_url(result.get("image_path")),
    })


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
_backtest_jobs = JobManager()


def _run_quick_backtest_job(ticker, max_windows):
    from backtesting.runner import quick_backtest
    result = quick_backtest(ticker, max_windows=max_windows)
    return {"ticker": ticker, "text": result["text"], "image_url": _to_url(result.get("image_path"))}


@app.route("/backtest", methods=["GET"])
def backtest():
    return render_template("backtest.html", active="backtest",
                            portfolio=simulation_store.get_portfolio(_user_id()))


@app.route("/backtest/run", methods=["POST"])
def backtest_run():
    """
    Kicks off a walk-forward backtest (several sequential Kronos calls,
    one per window -- easily the slowest single action in this app) in a
    background thread and returns a job id immediately instead of
    blocking the request. See /backtest/job/<id> to poll and
    /backtest/result/<id> to render the finished page -- same
    submit/poll/render-on-completion pattern used for /screener/run and
    /backtest/simulation/buy below.
    """
    ticker = (request.form.get("ticker") or "").strip().upper()
    max_windows = int(request.form.get("max_windows") or 15)
    if not ticker:
        return jsonify({"error": "Enter a ticker first."}), 400
    job_id = _backtest_jobs.submit(_run_quick_backtest_job, ticker, max_windows)
    return jsonify({"job_id": job_id})


@app.route("/backtest/job/<job_id>")
def backtest_job(job_id):
    return jsonify(_backtest_jobs.poll(job_id))


@app.route("/backtest/result/<job_id>")
def backtest_result(job_id):
    result = _backtest_jobs.get_result(job_id)
    if result is None:
        flash("That backtest result has expired or wasn't found -- please run it again.", "error")
        return redirect(url_for("backtest"))
    return render_template("backtest.html", active="backtest",
                            result_text=result["text"], result_ticker=result["ticker"],
                            image_url=result["image_url"],
                            portfolio=simulation_store.get_portfolio(_user_id()))


# ---------------------------------------------------------------------------
# Simulation -- paper trading with demo money (assistant/simulation.py).
# "Buy" a ticker at its real current price with fake cash, let it sit, and
# come back once the forecast's horizon has passed to see whether Kronos's
# call actually played out against real future prices -- a forward-looking
# complement to the historical walk-forward backtest above, not a
# replacement for it.
# ---------------------------------------------------------------------------
_simulation_jobs = JobManager()


def _run_simulation_buy_job(user_id, ticker, amount_type, amount):
    if amount_type == "shares":
        return simulation_store.buy(user_id, ticker, shares=amount)
    return simulation_store.buy(user_id, ticker, dollars=amount)


@app.route("/backtest/simulation/buy", methods=["POST"])
def simulation_buy():
    """
    Buying snapshots a real Kronos forecast (see
    assistant.simulation._snapshot_forecast) -- the same inference cost as
    any other forecast in the app, so this gets the same background-job
    treatment as /forecast/ticker and /backtest/run rather than blocking
    the request for however long that takes on your hardware.
    """
    ticker = (request.form.get("ticker") or "").strip().upper()
    amount_type = request.form.get("amount_type", "dollars")
    raw_amount = request.form.get("amount")

    if not ticker:
        return jsonify({"error": "Enter a ticker first."}), 400
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError):
        return jsonify({"error": "Enter a valid amount."}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero."}), 400

    job_id = _simulation_jobs.submit(_run_simulation_buy_job, _user_id(), ticker, amount_type, amount)
    return jsonify({"job_id": job_id})


@app.route("/backtest/simulation/job/<job_id>")
def simulation_job(job_id):
    status = _simulation_jobs.poll(job_id)
    if status["status"] == "done":
        position = status["result"]
        status["ticker"] = position["ticker"]
    return jsonify(status)


@app.route("/backtest/simulation/sell", methods=["POST"])
def simulation_sell():
    ticker = (request.form.get("ticker") or "").strip().upper()
    position_id = request.form.get("position_id") or None
    raw_shares = request.form.get("shares")
    shares = None
    if raw_shares:
        try:
            shares = float(raw_shares)
        except ValueError:
            flash("Enter a valid number of shares.", "error")
            return redirect(url_for("backtest") + "#simulation")

    try:
        simulation_store.sell(_user_id(), ticker, position_id=position_id, shares=shares)
        flash(f"Sold {ticker}.", "ok")
    except simulation_store.SimulationError as e:
        flash(str(e), "error")
    except Exception as e:
        flash(f"Sell failed: {e}", "error")
    return redirect(url_for("backtest") + "#simulation")


@app.route("/backtest/simulation/reset", methods=["POST"])
def simulation_reset():
    simulation_store.reset_portfolio(_user_id())
    flash("Demo portfolio reset.", "ok")
    return redirect(url_for("backtest") + "#simulation")


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
@app.route("/watchlist")
def watchlist():
    return render_template("watchlist.html", active="watchlist",
                            watchlist=watchlist_store.get(_user_id()),
                            auto_backups=storage_mod.list_backups(assistant_config.WATCHLIST_PATH))


@app.route("/watchlist/backup/now", methods=["POST"])
def watchlist_backup_now():
    """Manual, on-demand snapshot on top of the automatic ones taken on
    every edit and on server shutdown -- see assistant/storage.py."""
    storage_mod.snapshot_all(tag="manual")
    flash("Backup snapshot saved.", "ok")
    return redirect(url_for("watchlist"))


@app.route("/watchlist/backup/restore", methods=["POST"])
def watchlist_backup_restore():
    """Restore watchlists.json from one of its own rotating backups.
    Notes/entry zones are untouched -- only the ticker list itself."""
    backup_file = request.form.get("backup_file") or ""
    try:
        storage_mod.restore_backup(assistant_config.WATCHLIST_PATH, backup_file)
        flash("Watchlist restored from backup.", "ok")
    except Exception as e:
        flash(f"Couldn't restore that backup: {e}", "error")
    return redirect(url_for("watchlist"))


@app.route("/watchlist/correlation")
def watchlist_correlation():
    wl = watchlist_store.get(_user_id())
    if len(wl) < 2:
        flash("Add at least two tickers to your watchlist first.", "error")
        return redirect(url_for("watchlist"))
    corr_df, failed = portfolio_analysis.compute_correlation_matrix(wl)
    if corr_df is None:
        flash("Couldn't compute correlations -- not enough overlapping history.", "error")
        return redirect(url_for("watchlist"))
    text = portfolio_analysis.format_correlation_text(corr_df)
    if failed:
        text += f"\n(couldn't fetch: {', '.join(failed)})"
    image_path = portfolio_analysis.build_correlation_heatmap(corr_df)
    return render_template("watchlist.html", active="watchlist", watchlist=wl,
                            corr_text=text, corr_image_url=_to_url(image_path),
                            auto_backups=storage_mod.list_backups(assistant_config.WATCHLIST_PATH))


@app.route("/watchlist/export")
def watchlist_export():
    """
    Download everything for this user's watchlist -- tickers, notes, and
    entry zones -- as a single JSON file. Purely a backup/portability
    feature; doesn't affect what's stored server-side.
    """
    import json
    user_id = _user_id()
    payload = {
        "tickers": watchlist_store.get(user_id),
        "notes": watchlist_extras.get_all_notes(user_id),
        "entry_zones": watchlist_extras.get_all_entry_zones(user_id),
    }
    body = json.dumps(payload, indent=2)
    return Response(
        body, mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=kronos_watchlist_backup.json"},
    )


@app.route("/watchlist/import", methods=["POST"])
def watchlist_import():
    """
    Restore/merge a previously exported watchlist backup. Always additive:
    tickers are added (not replacing the current list), and notes/entry
    zones only fill in tickers that don't already have one -- this import
    can never wipe out anything currently saved.
    """
    import json
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("Choose a backup JSON file first.", "error")
        return redirect(url_for("watchlist"))

    try:
        payload = json.loads(file.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        flash("That doesn't look like a valid backup file.", "error")
        return redirect(url_for("watchlist"))

    user_id = _user_id()
    added = 0
    for ticker in payload.get("tickers", []):
        watchlist_store.add(user_id, ticker)
        added += 1

    existing_notes = watchlist_extras.get_all_notes(user_id)
    for ticker, note in (payload.get("notes") or {}).items():
        if ticker not in existing_notes:  # never overwrite a note you already have
            watchlist_extras.set_note(user_id, ticker, note)

    existing_zones = watchlist_extras.get_all_entry_zones(user_id)
    for ticker, zone in (payload.get("entry_zones") or {}).items():
        if ticker not in existing_zones and zone:  # never overwrite an existing zone
            watchlist_extras.set_entry_zone(user_id, ticker, zone.get("low"), zone.get("high"))

    flash(f"Imported {added} ticker(s) from backup (existing notes/zones were kept, not overwritten).", "ok")
    return redirect(url_for("watchlist"))


@app.route("/watchlist/add", methods=["POST"])
def watchlist_add():
    ticker = (request.form.get("ticker") or "").strip().upper()
    if ticker:
        watchlist_store.add(_user_id(), ticker)
    return redirect(url_for("watchlist"))


@app.route("/watchlist/remove", methods=["POST"])
def watchlist_remove():
    ticker = (request.form.get("ticker") or "").strip().upper()
    if ticker:
        watchlist_store.remove(_user_id(), ticker)
    return redirect(url_for("watchlist"))


@app.route("/api/watchlist/details")
def api_watchlist_details():
    """
    Full per-ticker enrichment for the watchlist page: latest price,
    upcoming earnings date/quarter, saved note, and saved entry zone (+
    whether the current price is inside it). Called once when the page
    loads -- this does one or more yfinance calls per ticker, so it's kept
    separate from the lightweight /api/watchlist/prices used for polling.
    """
    user_id = _user_id()
    tickers = watchlist_store.get(user_id)
    notes = watchlist_extras.get_all_notes(user_id)
    zones = watchlist_extras.get_all_entry_zones(user_id)

    rows = []
    for t in tickers:
        row = {"ticker": t, "note": notes.get(t, ""), "entry_zone": zones.get(t)}
        try:
            price_info = fundamentals.get_live_price(t)
        except ValueError:
            price_info = None
        row["price"] = price_info
        row["zone_status"] = (
            watchlist_extras.check_zone_status(price_info["price"], zones.get(t))
            if price_info and zones.get(t) else None
        )
        try:
            earnings_info = fundamentals.get_next_earnings_info(t)
            row["earnings"] = {
                "date": str(earnings_info["date"]) if earnings_info["date"] else None,
                "quarter": earnings_info["quarter"],
                "days_until": earnings_info["days_until"],
            }
        except ValueError:
            row["earnings"] = {"date": None, "quarter": None, "days_until": None}
        rows.append(row)

    return jsonify({"tickers": rows})


@app.route("/api/watchlist/prices")
def api_watchlist_prices():
    """Lightweight endpoint for periodic polling -- just prices, no
    earnings/notes lookups, so it's cheap enough to call every 30-60s."""
    tickers = watchlist_store.get(_user_id())
    prices = {}
    for t in tickers:
        try:
            prices[t] = fundamentals.get_live_price(t)
        except ValueError:
            prices[t] = None
    return jsonify({"prices": prices})


@app.route("/watchlist/note", methods=["POST"])
def watchlist_note():
    payload = request.get_json(silent=True) or {}
    ticker = (payload.get("ticker") or "").strip().upper()
    text = payload.get("note", "")
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    saved = watchlist_extras.set_note(_user_id(), ticker, text)
    return jsonify({"ticker": ticker, "note": saved})


@app.route("/watchlist/entry_zone", methods=["POST"])
def watchlist_entry_zone():
    payload = request.get_json(silent=True) or {}
    ticker = (payload.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    if payload.get("clear"):
        watchlist_extras.clear_entry_zone(_user_id(), ticker)
        return jsonify({"ticker": ticker, "entry_zone": None})
    try:
        low = float(payload.get("low"))
        high = float(payload.get("high"))
    except (TypeError, ValueError):
        return jsonify({"error": "low/high must be numbers"}), 400
    zone = watchlist_extras.set_entry_zone(_user_id(), ticker, low, high)
    return jsonify({"ticker": ticker, "entry_zone": zone})


if __name__ == "__main__":
    port = int(os.getenv("WEBAPP_PORT", "5050"))
    debug = os.getenv("WEBAPP_DEBUG", "true").lower() in ("1", "true", "yes")
    # The auto-reloader watches every imported module's file, including
    # everything under the venv's site-packages if the venv lives inside
    # the project folder (common setup, especially on Windows) -- that
    # makes it "restart" on unrelated numpy/scipy/torch file changes,
    # which is disruptive here since a restart means Kronos's model gets
    # reloaded from scratch. Off by default; set WEBAPP_RELOADER=true if
    # you specifically want auto-restart-on-code-change during development
    # (and consider moving kronos_env/ outside the project folder if so).
    use_reloader = os.getenv("WEBAPP_RELOADER", "false").lower() in ("1", "true", "yes")
    print(f"Kronos web app -- http://127.0.0.1:{port} (debug={debug}, reloader={use_reloader})")
    if debug:
        print("Running Flask's built-in dev server. For anything beyond your own "
              "machine, set WEBAPP_DEBUG=false and run behind a real WSGI server "
              "(gunicorn/waitress) -- see DEPLOYMENT.md.")
    # threaded=True is required, not just nice-to-have: chat replies run in a
    # background thread (see _run_chat_job above) so they survive the user
    # navigating away from /chat, and the polling requests that check on
    # them need to be served concurrently with whatever else is happening,
    # not queued behind a single-threaded dev server.
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=use_reloader, threaded=True)
