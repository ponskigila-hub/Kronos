"""
Wraps KronosPredictor.predict() with:
  - automatic future-date generation
  - continuity anchoring (see _anchor_to_last_close) to remove level-jump
    artifacts between the last real price and the first forecasted step
  - internal sample averaging (Kronos's own `sample_count`) to reduce
    single-sample noise
  - optional multi-run sampling to build a confidence band (independent
    predict() calls, percentile-banded across runs)
"""
import numpy as np
import pandas as pd

from .model_loader import get_predictor
from .config import (
    DEFAULT_PRED_LEN,
    DEFAULT_SAMPLE_RUNS,
    DEFAULT_KRONOS_SAMPLE_COUNT,
    DEFAULT_KRONOS_T,
    FORECAST_DRIFT_BLEND,
)
from . import forecast_cache

FEATURE_COLS = ["open", "high", "low", "close", "volume", "amount"]
OHLC_COLS = ["open", "high", "low", "close"]


def _future_dates(last_date, pred_len):
    return pd.date_range(start=last_date + pd.offsets.BDay(1), periods=pred_len, freq="B")


def _drift_path(last_close, hist_closes, pred_len):
    """Simple linear drift baseline from recent average daily change."""
    if len(hist_closes) < 2:
        return np.full(pred_len, last_close)
    # Use last ~20 trading days for a local drift estimate (more reactive
    # than full-history mean, less noisy than 1-day return).
    window = min(20, len(hist_closes) - 1)
    recent = hist_closes[-(window + 1) :]
    avg_drift = float(np.mean(np.diff(recent)))
    return last_close + avg_drift * np.arange(1, pred_len + 1)


def _blend_with_drift(pred_df, last_close, hist_closes, alpha):
    """
    Soft-blend Kronos close path with a local drift baseline.
    alpha=0 keeps pure Kronos; alpha=1 is pure drift. OHLC other columns
    are shifted by the same close delta so the candle structure stays
    consistent with the blended close.
    """
    if alpha <= 0:
        return pred_df
    alpha = min(1.0, float(alpha))
    pred_len = len(pred_df)
    drift = _drift_path(last_close, hist_closes, pred_len)
    kronos_close = pred_df["close"].values.astype(float)
    blended = (1.0 - alpha) * kronos_close + alpha * drift
    delta = blended - kronos_close
    out = pred_df.copy()
    out["close"] = blended
    for col in ("open", "high", "low"):
        if col in out.columns:
            out[col] = out[col].values.astype(float) + delta
    return out


def _anchor_to_last_close(pred_df, last_close):
    """
    Kronos denormalizes each forecast window using that window's own
    mean/std, which can leave a visible discontinuity between the last real
    close and the first forecasted step (the forecast "jumps" to a
    different price level even though the shape of the predicted path is
    reasonable). This shifts every OHLC column by a constant offset so the
    forecast continues smoothly from the last known price, without altering
    the predicted day-to-day changes at all -- a standard continuity/bias
    correction, not a change to what the model actually predicted about
    direction or magnitude of moves.
    """
    offset = last_close - float(pred_df["close"].iloc[0])
    pred_df = pred_df.copy()
    for col in OHLC_COLS:
        if col in pred_df.columns:
            pred_df[col] = pred_df[col] + offset
    return pred_df


def _historical_volatility_band(pred_df, hist_closes):
    """Approximate a price range from recent daily log-return volatility.

    This is an analytical range, not a calibrated model confidence interval.
    It deliberately leaves the central forecast path unchanged.
    """
    prices = np.asarray(hist_closes, dtype=float)
    prices = prices[np.isfinite(prices) & (prices > 0)]
    log_returns = np.diff(np.log(prices))
    # Use the latest 20 returns, or all available returns for short histories.
    log_returns = log_returns[-20:]
    sigma = float(np.std(log_returns, ddof=1)) if len(log_returns) >= 2 else 0.0
    t = np.arange(1, len(pred_df) + 1, dtype=float)
    spread = pred_df["close"].to_numpy(dtype=float) * 1.28 * sigma * np.sqrt(t)
    return (
        pd.DataFrame({"timestamps": pred_df["timestamps"].to_numpy(),
                      "close": pred_df["close"].to_numpy(dtype=float) - spread}),
        pd.DataFrame({"timestamps": pred_df["timestamps"].to_numpy(),
                      "close": pred_df["close"].to_numpy(dtype=float) + spread}),
    )


def uncertainty_pct_from_bands(low_df, high_df, reference_close):
    """Full horizon-end band width as a percent of the last observed close.

    This is a sizing/context statistic, not a calibrated probability. Sampled
    multi-run bands and the single-run historical-volatility band are distinct
    estimates and should not be interpreted as equivalent confidence levels.
    """
    try:
        reference_close = float(reference_close)
        if reference_close <= 0 or low_df is None or high_df is None:
            return None
        low = float(low_df["close"].iloc[-1])
        high = float(high_df["close"].iloc[-1])
        if not np.isfinite([reference_close, low, high]).all():
            return None
        return round(max(0.0, high - low) / reference_close * 100.0, 4)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        return None


def confidence_scale_from_uncertainty(uncertainty_pct):
    """Conservative [0.5, 1.0] risk-budget multiplier from band width (% points)."""
    try:
        value = float(uncertainty_pct)
        if not np.isfinite(value):
            return 1.0
    except (TypeError, ValueError):
        return 1.0
    if value <= 15.0:
        return 1.0
    return round(max(0.5, 1.0 - (value - 15.0) / 30.0), 4)


def run_forecast(hist_df, pred_len=None, n_runs=None, lookback=None, T=None, top_p=0.9,
                  sample_count=None, anchor_to_last_close=True):
    """
    hist_df: cleaned history from assistant.data_fetcher.fetch_history
             (must contain 'timestamps' + FEATURE_COLS)

    sample_count: how many samples Kronos averages internally per predict()
                  call (its own built-in noise reduction). Higher = smoother,
                  slower. Defaults to config.DEFAULT_KRONOS_SAMPLE_COUNT.
    n_runs: how many *independent* predict() calls to make on top of that,
            used only to build a low/high confidence band across runs.
    anchor_to_last_close: apply the continuity correction described in
            _anchor_to_last_close(). On by default -- turn off only if you
            specifically want Kronos's raw, unadjusted output (e.g. to
            diagnose the model itself rather than evaluate trading use).

    Returns a dict:
        {
          "pred_df": DataFrame[timestamps, open, high, low, close, volume, amount],  (median across runs)
          "mean_df": DataFrame[timestamps, close] or None (mean across runs, if n_runs > 1),
          "low_df":  DataFrame (sampled percentile or historical-volatility range),
          "high_df": DataFrame (sampled percentile or historical-volatility range),
          "band_source": "sampled" or "analytical_vol",
          "all_runs": list of DataFrames, one per sampled path (always has
                       at least 1; useful for a spaghetti-style plot),
          "lookback_used": int,
          "n_runs": int,
          "context_start": Timestamp of the first date actually fed to the model,
          "forecast_start": Timestamp of the last known real date,
        }
    """
    pred_len = pred_len or DEFAULT_PRED_LEN
    n_runs = n_runs or DEFAULT_SAMPLE_RUNS
    sample_count = sample_count or DEFAULT_KRONOS_SAMPLE_COUNT
    T = DEFAULT_KRONOS_T if T is None else T
    predictor = get_predictor()

    lookback = lookback or min(predictor.max_context, len(hist_df))
    lookback = min(lookback, len(hist_df))

    x_df = hist_df.iloc[-lookback:][FEATURE_COLS].copy()
    x_timestamp = hist_df.iloc[-lookback:]["timestamps"].copy()
    last_close = float(x_df["close"].iloc[-1])
    hist_closes = x_df["close"].values.astype(float)
    last_date = hist_df["timestamps"].max()
    future_dates = _future_dates(last_date, pred_len)
    y_timestamp = pd.Series(future_dates)
    drift_blend = FORECAST_DRIFT_BLEND

    cache_key = forecast_cache.make_key(
        x_df, x_timestamp, pred_len, n_runs, lookback, T, top_p,
        sample_count, anchor_to_last_close, drift_blend=drift_blend,
        band_version=2,
    )
    cached = forecast_cache.get(cache_key)
    if cached is not None:
        return cached

    runs = []
    for i in range(max(1, n_runs)):
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=T,
            top_p=top_p,
            sample_count=sample_count,
            verbose=False,
        )
        pred_df = pred_df.iloc[:pred_len].copy()
        pred_df["timestamps"] = future_dates[: len(pred_df)]
        if anchor_to_last_close:
            pred_df = _anchor_to_last_close(pred_df, last_close)
        # Light ensemble with local drift — applied per-run so the band
        # also reflects the blended distribution.
        pred_df = _blend_with_drift(pred_df, last_close, hist_closes, drift_blend)
        runs.append(pred_df.reset_index(drop=True))

    main_pred = runs[0]
    low_df = high_df = mean_df = None
    band_source = "sampled" if len(runs) > 1 else "analytical_vol"

    if len(runs) > 1:
        stacked_close = np.stack([r["close"].values for r in runs], axis=0)
        median_close = np.median(stacked_close, axis=0)
        mean_close = np.mean(stacked_close, axis=0)
        low_close = np.percentile(stacked_close, 10, axis=0)
        high_close = np.percentile(stacked_close, 90, axis=0)

        main_pred = main_pred.copy()
        main_pred["close"] = median_close
        # Keep OHLC consistent with median close (shift by delta from first run)
        if "open" in main_pred.columns:
            delta = median_close - runs[0]["close"].values
            for col in ("open", "high", "low"):
                if col in main_pred.columns:
                    main_pred[col] = main_pred[col].values.astype(float) + delta

        low_df = pd.DataFrame({"timestamps": future_dates, "close": low_close})
        high_df = pd.DataFrame({"timestamps": future_dates, "close": high_close})
        mean_df = pd.DataFrame({"timestamps": future_dates, "close": mean_close})
    else:
        low_df, high_df = _historical_volatility_band(main_pred, hist_closes)

    uncertainty_pct = uncertainty_pct_from_bands(low_df, high_df, last_close)

    result = {
        "pred_df": main_pred,
        "mean_df": mean_df,          # None if n_runs == 1 -- mean across all sampled paths
        "low_df": low_df,
        "high_df": high_df,
        "all_runs": runs,            # every individual sampled path, for spaghetti-style plots
        "lookback_used": lookback,
        "n_runs": len(runs),
        "band_source": band_source,
        "uncertainty_pct": uncertainty_pct,
        "uncertainty_reference_close": last_close,
        "context_start": x_timestamp.iloc[0],  # first date actually fed to the model
        "forecast_start": last_date,           # last known real date (where forecasting begins)
    }
    forecast_cache.set(cache_key, result)
    return result
