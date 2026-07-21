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
    jsonify, flash, send_from_directory, abort,
)

from assistant.core_assistant import StockAssistant
from assistant import watchlist as watchlist_store
from assistant import data_fetcher, indicators, forecaster as forecaster_mod, charts, config as assistant_config
from assistant.data_fetcher import TickerNotFoundError
from backtesting.data_loaders import CSVLoader

app = Flask(__name__)
app.secret_key = os.getenv("WEBAPP_SECRET_KEY", "kronos-dev-secret-change-me")

bot = StockAssistant()

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


@app.route("/api/chat", methods=["POST"])
def api_chat():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("message") or "").strip()
    if not text:
        return jsonify({"text": "Say something and I'll take a look."})

    result = bot.handle_message(_user_id(), text)
    return jsonify({
        "text": result.get("text", ""),
        "image_url": _to_url(result.get("image_path")),
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

    if not ticker:
        flash("Enter a ticker first.", "error")
        return redirect(url_for("forecast"))

    try:
        hist_df = data_fetcher.fetch_history(ticker, lookback_days=lookback)
        ind_df = indicators.compute_indicators(hist_df)
        fc = forecaster_mod.run_forecast(hist_df, pred_len=pred_len)
        image_path = charts.build_forecast_png(ticker, hist_df, fc)

        last_close = float(hist_df["close"].iloc[-1])
        forecast_close = float(fc["pred_df"]["close"].iloc[-1])
        pct = (forecast_close - last_close) / last_close * 100
        result_text = (
            f"{ticker}: {last_close:.2f} -> {forecast_close:.2f} over {pred_len} trading days "
            f"({pct:+.2f}%). Lookback used: {fc['lookback_used']} days."
        )
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


if __name__ == "__main__":
    port = int(os.getenv("WEBAPP_PORT", "5050"))
    print(f"Kronos web app -- http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
