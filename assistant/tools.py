"""
Structured, compact financial "tools" for assistant/copilot.py's LLM
tool-selection layer.

Every function here:
  - Takes plain strings/ints, not DataFrames.
  - Returns a small JSON-safe dict (never a DataFrame, never a Plotly
    figure) -- the LLM only ever sees numbers and labels it can reason
    about and mention in prose, never raw OHLCV rows. This is the
    "STRUCTURED TOOL RESULTS" requirement from the project brief: giving
    an LLM a full price history to summarize invites it to eyeball-average
    or misread the data and state something as fact that isn't; a
    pre-computed dict has no such failure mode.
  - Wraps existing, already-correct modules (forecaster, indicators,
    news, fundamentals, backtesting) rather than recomputing anything --
    this file adds a thin JSON-shaping layer, not new financial logic.
  - Never raises for "normal" failure modes (bad ticker, no data) --
    returns {"error": "..."} instead, so a single failed tool call
    doesn't blow up the whole copilot turn; the model can see the error
    and either try something else or say so in its reply.

These are also usable directly (not just via the LLM), e.g. from a future
API endpoint that wants the same compact shape without going through
chat.
"""
from . import data_fetcher, indicators, forecaster, news, fundamentals
from .data_fetcher import TickerNotFoundError


def _safe(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except TickerNotFoundError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"{fn.__name__} failed: {e}"}
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@_safe
def get_kronos_forecast(ticker: str, horizon: int = 14) -> dict:
    """Run a Kronos forecast for a ticker and return a compact summary:
    current price, forecast price at the given horizon, expected return,
    and trend direction. Use this whenever the user asks what Kronos
    predicts, or references a forecast, price target, or expected move."""
    hist_df = data_fetcher.fetch_history(ticker)
    fc = forecaster.run_forecast(hist_df, pred_len=horizon, n_runs=1)
    current_price = float(hist_df["close"].iloc[-1])
    forecast_price = float(fc["pred_df"]["close"].iloc[-1])
    expected_return = (forecast_price - current_price) / current_price
    return {
        "ticker": ticker.upper(),
        "current_price": round(current_price, 2),
        "forecast_horizon_days": horizon,
        "forecast_price": round(forecast_price, 2),
        "expected_return_pct": round(expected_return * 100, 2),
        "trend": "bullish" if expected_return > 0.005 else "bearish" if expected_return < -0.005 else "flat",
        "lookback_days_used": fc["lookback_used"],
    }


@_safe
def get_technical_indicators(ticker: str) -> dict:
    """Return the latest technical indicator readings for a ticker: RSI,
    MACD (and whether it's signaling positive/negative momentum), SMA20/50,
    Bollinger Bands, ATR (volatility), and volume vs. its 20-day average.
    Use this when the user asks about momentum, overbought/oversold
    conditions, or "why" a stock is behaving a certain way technically."""
    hist_df = data_fetcher.fetch_history(ticker)
    ind_df = indicators.compute_indicators(hist_df)
    latest = indicators.summarize_latest(ind_df)
    macd_signal = None
    if latest.get("macd") is not None and latest.get("macd_signal") is not None:
        macd_signal = "positive" if latest["macd"] > latest["macd_signal"] else "negative"
    above_volume_avg = None
    if latest.get("volume_sma_20"):
        above_volume_avg = latest["volume"] > latest["volume_sma_20"]
    return {
        "ticker": ticker.upper(),
        "close": latest["close"],
        "rsi_14": latest["rsi_14"],
        "macd_signal": macd_signal,
        "sma_20": latest["sma_20"],
        "sma_50": latest["sma_50"],
        "above_sma_20": (latest["close"] > latest["sma_20"]) if latest.get("sma_20") else None,
        "bollinger_upper": latest["bb_upper"],
        "bollinger_lower": latest["bb_lower"],
        "atr_14": latest["atr_14"],
        "volume_above_20d_average": above_volume_avg,
    }


@_safe
def get_prediction_performance(ticker: str) -> dict:
    """Return Kronos's historical forecasting accuracy for this specific
    ticker (directional accuracy, MAE, RMSE) from a quick walk-forward
    backtest. Use this when the user asks how reliable/accurate the model
    has been, or how it's performed historically on this stock."""
    from backtesting.runner import quick_backtest
    # Fewer windows than the "backtest" chat intent's default (see
    # assistant/config.py's BACKTEST_QUICK_MAX_WINDOWS) -- this runs
    # inside an LLM-driven tool call that's already budgeted against
    # COPILOT_TIMEOUT_SECONDS, so it needs to be fast, not exhaustive.
    # A user who wants the full picture can still just ask to "backtest
    # AAPL" directly, which uses the standard, more thorough settings.
    result = quick_backtest(ticker, max_windows=5, include_benchmarks=False)
    metrics_df = result["metrics_df"]
    kronos_rows = metrics_df[metrics_df["model"] == "Kronos"] if not metrics_df.empty else metrics_df
    if kronos_rows.empty:
        return {"error": f"Not enough history to backtest '{ticker}' yet."}
    return {
        "ticker": ticker.upper(),
        "windows_evaluated": int(kronos_rows["n_predictions"].sum()),
        "avg_directional_accuracy_pct": round(float(kronos_rows["direction_accuracy"].mean()), 1),
        "avg_mae": round(float(kronos_rows["mae"].mean()), 4),
        "avg_rmse": round(float(kronos_rows["rmse"].mean()), 4),
    }


@_safe
def get_news_sentiment(ticker: str, limit: int = 5) -> dict:
    """Return recent headlines for a ticker plus an aggregate sentiment
    label (mostly positive / mixed-neutral / mostly negative). Use this
    when the user asks about news, sentiment, or recent events."""
    items, summary = news.get_news(ticker, limit=limit)
    return {
        "ticker": ticker.upper(),
        "sentiment_label": summary["label"],
        "sentiment_score": summary["avg_score"],
        "headline_count": len(items),
        "headlines": [i["title"] for i in items[:limit]],
    }


@_safe
def get_fundamentals(ticker: str) -> dict:
    """Return key valuation/company fundamentals: P/E ratio, market cap,
    sector, profit margin, dividend yield, 52-week range. Use this when
    the user asks about valuation, whether a stock is "expensive", or
    company-level fundamentals rather than price action."""
    return fundamentals.get_fundamentals(ticker)


@_safe
def compare_stocks(ticker_a: str, ticker_b: str, horizon: int = 14) -> dict:
    """Compare Kronos forecasts for two tickers side by side over the same
    horizon. Use this whenever the user asks to compare two stocks or
    asks which of two options looks stronger."""
    a = get_kronos_forecast(ticker_a, horizon=horizon)
    b = get_kronos_forecast(ticker_b, horizon=horizon)
    if "error" in a:
        return {"error": f"{ticker_a}: {a['error']}"}
    if "error" in b:
        return {"error": f"{ticker_b}: {b['error']}"}
    stronger = None
    if a["expected_return_pct"] != b["expected_return_pct"]:
        stronger = a["ticker"] if a["expected_return_pct"] > b["expected_return_pct"] else b["ticker"]
    return {ticker_a.upper(): a, ticker_b.upper(): b, "stronger_forecast": stronger}


# Registry the copilot layer iterates over to build the tool schema and
# dispatch calls by name. Kept as a plain dict (not a decorator-based
# auto-registration system) -- there are 6 tools, adding a 7th is a
# one-line addition here, and an explicit list is easier to audit for
# "does the LLM have access to something it shouldn't" than implicit
# registration would be.
TOOL_REGISTRY = {
    "get_kronos_forecast": get_kronos_forecast,
    "get_technical_indicators": get_technical_indicators,
    "get_prediction_performance": get_prediction_performance,
    "get_news_sentiment": get_news_sentiment,
    "get_fundamentals": get_fundamentals,
    "compare_stocks": compare_stocks,
}
