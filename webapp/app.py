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
import uuid

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
from assistant.data_fetcher import TickerNotFoundError
from assistant.ticker_directory import search_tickers
from assistant.conversation import get_context
from backtesting.data_loaders import CSVLoader

app = Flask(__name__)
app.secret_key = os.getenv("WEBAPP_SECRET_KEY", "kronos-dev-secret-change-me")

bot = StockAssistant()


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
    payload = request.get_json(silent=True) or {}
    text = (payload.get("message") or "").strip()

    # A mode toggle from the UI switch arrives as an explicit field rather
    # than parsed from the message text -- feed it through the same
    # "set_mode"-style text so core_assistant's normal path handles it.
    # Resolved before the empty-text check below, since a pure mode-toggle
    # request has no "message" at all.
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
# Forecast -- ticker and CSV upload
# ---------------------------------------------------------------------------
@app.route("/forecast")
def forecast():
    return render_template("forecast.html", active="forecast")


@app.route("/forecast/ticker", methods=["POST"])
def forecast_ticker():
    ticker = (request.form.get("ticker") or "").strip().upper()
    pred_len = int(request.form.get("pred_len") or 30)
    lookback = int(request.form.get("lookback") or 400)
    detailed = request.form.get("detailed") == "on"

    if not ticker:
        flash("Enter a ticker first.", "error")
        return redirect(url_for("forecast"))

    try:
        hist_df = data_fetcher.fetch_history(ticker, lookback_days=lookback)
        ind_df = indicators.compute_indicators(hist_df)
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
        return render_template("forecast.html", active="forecast",
                                result_text=result_text, result_ticker=ticker,
                                image_url=_to_url(image_path))
    except TickerNotFoundError as e:
        flash(str(e), "error")
        return redirect(url_for("forecast"))
    except Exception as e:
        flash(f"Forecast failed: {e}", "error")
        return redirect(url_for("forecast"))


@app.route("/forecast/csv", methods=["POST"])
def forecast_csv():
    file = request.files.get("file")
    label = (request.form.get("name") or "UPLOAD").strip().upper() or "UPLOAD"
    pred_len = int(request.form.get("pred_len") or 30)

    if not file or file.filename == "":
        flash("Choose a CSV file first.", "error")
        return redirect(url_for("forecast"))

    try:
        import pandas as pd
        raw_df = pd.read_csv(file)
        hist_df = CSVLoader().normalize(raw_df)
        if len(hist_df) < 30:
            raise ValueError("Need at least 30 rows of history to forecast anything useful.")

        ind_df = indicators.compute_indicators(hist_df)
        fc = forecaster_mod.run_forecast(hist_df, pred_len=pred_len)
        image_path = charts.build_forecast_png(label, hist_df, fc)

        last_close = float(hist_df["close"].iloc[-1])
        forecast_close = float(fc["pred_df"]["close"].iloc[-1])
        pct = (forecast_close - last_close) / last_close * 100
        result_text = (
            f"{label}: {last_close:.2f} -> {forecast_close:.2f} over {pred_len} trading days "
            f"({pct:+.2f}%). Rows read from CSV: {len(hist_df)}, lookback used: {fc['lookback_used']} days."
        )
        return render_template("forecast.html", active="forecast",
                                result_text=result_text, result_ticker=label,
                                image_url=_to_url(image_path))
    except Exception as e:
        flash(f"Couldn't process that CSV: {e}", "error")
        return redirect(url_for("forecast"))


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
@app.route("/backtest", methods=["GET", "POST"])
def backtest():
    if request.method == "GET":
        return render_template("backtest.html", active="backtest")

    ticker = (request.form.get("ticker") or "").strip().upper()
    max_windows = int(request.form.get("max_windows") or 15)
    if not ticker:
        flash("Enter a ticker first.", "error")
        return redirect(url_for("backtest"))

    try:
        # Imported lazily, same reasoning as core_assistant._backtest --
        # scipy/statsmodels only need to load when this route is used.
        from backtesting.runner import quick_backtest
        result = quick_backtest(ticker, max_windows=max_windows)
        return render_template("backtest.html", active="backtest",
                                result_text=result["text"], result_ticker=ticker,
                                image_url=_to_url(result.get("image_path")))
    except Exception as e:
        flash(f"Backtest failed: {e}", "error")
        return redirect(url_for("backtest"))


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
@app.route("/watchlist")
def watchlist():
    return render_template("watchlist.html", active="watchlist",
                            watchlist=watchlist_store.get(_user_id()))


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
                            corr_text=text, corr_image_url=_to_url(image_path))


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
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=use_reloader)
