"""
Runs the existing Kronos forecasting pipeline (assistant.forecaster) on
just the screener's top-ranked candidates -- never the whole universe
(project brief #12). assistant.forecaster / assistant.model_loader are
imported lazily inside run_for_candidates() so the heavy torch/model load
only happens if the Kronos stage is actually used.

Runs strictly sequentially: KronosPredictor is a single cached-singleton
model (see assistant/model_loader.py), so there's nothing to gain from
threading here the way screener/data.py threads plain HTTP downloads --
it would just contend for the same CPU/GPU resources.
"""


def run_for_candidates(candidates, history_cache, pred_len=30, n_runs=1, progress_cb=None):
    """
    candidates: ordered list of ticker symbols (already technically ranked --
                typically SCREENER_CONFIG["preselection_count"] of them)
    history_cache: {ticker: DataFrame} already-downloaded history, reused
                   here instead of re-fetching (screener/data.py already
                   pulled it for the technical stage)

    Returns {ticker: {
        "current_price", "forecast_price", "expected_return", "direction"
        ("up"/"down"/"flat"), "pred_len", "lookback_used", "error"
    }}. A per-ticker "error" (insufficient history, model failure) never
    aborts the rest of the batch.
    """
    from ..forecaster import run_forecast

    results = {}
    total = len(candidates)
    for i, ticker in enumerate(candidates, start=1):
        hist_df = history_cache.get(ticker)
        if hist_df is None or len(hist_df) < 30:
            results[ticker] = {"error": "Not enough history for Kronos to run on.",
                                "expected_return": None}
        else:
            try:
                fc = run_forecast(hist_df, pred_len=pred_len, n_runs=n_runs)
                last_close = float(hist_df["close"].iloc[-1])
                forecast_close = float(fc["pred_df"]["close"].iloc[-1])
                expected_return = (forecast_close - last_close) / last_close
                direction = "up" if expected_return > 0.01 else ("down" if expected_return < -0.01 else "flat")
                results[ticker] = {
                    "current_price": last_close,
                    "forecast_price": forecast_close,
                    "expected_return": expected_return,
                    "direction": direction,
                    "pred_len": pred_len,
                    "lookback_used": fc.get("lookback_used"),
                    "error": None,
                }
            except Exception as e:
                results[ticker] = {"error": str(e), "expected_return": None}
        if progress_cb:
            try:
                progress_cb(i, total, ticker)
            except Exception:
                pass
    return results
