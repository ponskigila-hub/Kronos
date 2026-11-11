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
    FORECAST_VOL_DAMPING,
)
from . import forecast_cache

FEATURE_COLS = ["open", "high", "low", "close", "volume", "amount"]
OHLC_COLS = ["open", "high", "low", "close"]


def _future_dates(last_date, pred_len):
    return pd.date_range(start=last_date + pd.offsets.BDay(1), periods=pred_len, freq="B")


def _mean_daily_change(hist_closes, window):
    """Average daily price change over the last `window` steps, or None if short."""
    if len(hist_closes) < window + 1:
        return None
    recent = hist_closes[-(window + 1):]
    return float(np.mean(np.diff(recent)))


def _vol_ratio(hist_closes):
    """Recent EWMA vol / 60d return std. 1.0 when data is too short."""
    if len(hist_closes) < 5:
        return 1.0
    rets = np.diff(hist_closes) / np.clip(hist_closes[:-1], 1e-12, None)
    rets = rets[np.isfinite(rets)]
    if len(rets) < 5:
        return 1.0
    # EWMA variance (span ~10)
    alpha = 2.0 / (10.0 + 1.0)
    var = float(rets[0] ** 2)
    for r in rets[1:]:
        var = alpha * float(r) ** 2 + (1.0 - alpha) * var
    recent = float(np.sqrt(max(var, 0.0)))
    tail = rets[-min(60, len(rets)):]
    base = float(np.std(tail, ddof=1)) if len(tail) > 1 else recent
    if base <= 1e-12:
        return 1.0
    return recent / base


def _daily_return_sigma(hist_closes):
    """Sample std of simple daily returns (price units relative)."""
    if len(hist_closes) < 3:
        return 0.0
    rets = np.diff(hist_closes) / np.clip(hist_closes[:-1], 1e-12, None)
    rets = rets[np.isfinite(rets)]
    if len(rets) < 2:
        return 0.0
    return float(np.std(rets, ddof=1))


def _drift_path(last_close, hist_closes, pred_len, vol_damping=None):
    """Multi-horizon volatility-adjusted linear drift baseline.

    Weighted mean of daily changes over 5d (0.50), 20d (0.35), and 60d (0.15).
    When recent EWMA vol rises vs the 60-day baseline, the slope is damped by
    1 / (1 + FORECAST_VOL_DAMPING * vol_ratio) so spikes are not extrapolated.
    """
    if len(hist_closes) < 2:
        return np.full(pred_len, last_close)

    if vol_damping is None:
        vol_damping = FORECAST_VOL_DAMPING

    windows = ((5, 0.50), (20, 0.35), (60, 0.15))
    parts = []
    for window, weight in windows:
        mean_ch = _mean_daily_change(hist_closes, window)
        if mean_ch is not None:
            parts.append((weight, mean_ch))

    if not parts:
        # Fallback: mean of all available daily changes
        avg_drift = float(np.mean(np.diff(hist_closes)))
    else:
        w_sum = sum(w for w, _ in parts)
        avg_drift = sum(w * d for w, d in parts) / w_sum

    ratio = _vol_ratio(hist_closes)
    damp = 1.0 / (1.0 + float(vol_damping) * float(ratio)) if vol_damping else 1.0
    avg_drift = avg_drift * damp
    return last_close + avg_drift * np.arange(1, pred_len + 1)


def confidence_scale_from_uncertainty(uncertainty_pct):
    """Map forecast uncertainty_pct to a [0.5, 1.0] position-size scale."""
    if uncertainty_pct is None:
        return 1.0
    try:
        u = float(uncertainty_pct)
    except (TypeError, ValueError):
        return 1.0
    if u > 15.0:
        return max(0.5, 1.0 - (u - 15.0) / 30.0)
    return 1.0


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
          "low_df":  DataFrame or None (10th percentile close, if n_runs > 1),
          "high_df": DataFrame or None (90th percentile close, if n_runs > 1),
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
        vol_damping=FORECAST_VOL_DAMPING,
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
    uncertainty_pct = 0.0

    if len(runs) > 1:
        stacked_close = np.stack([r["close"].values for r in runs], axis=0)
        median_close = np.median(stacked_close, axis=0)
        mean_close = np.mean(stacked_close, axis=0)
        low_close = np.percentile(stacked_close, 10, axis=0)
        high_close = np.percentile(stacked_close, 90, axis=0)

        main_pred = main_pred.copy()
        main_pred["close"] = median_close
        if "open" in main_pred.columns:
            delta = median_close - runs[0]["close"].values
            for col in ("open", "high", "low"):
                if col in main_pred.columns:
                    main_pred[col] = main_pred[col].values.astype(float) + delta

        low_df = pd.DataFrame({"timestamps": future_dates[:len(low_close)], "close": low_close})
        high_df = pd.DataFrame({"timestamps": future_dates[:len(high_close)], "close": high_close})
        mean_df = pd.DataFrame({"timestamps": future_dates[:len(mean_close)], "close": mean_close})
        if last_close > 0:
            uncertainty_pct = float((high_close[-1] - low_close[-1]) / last_close * 100.0)
    else:
        # Analytical P10/P90 when only 1 run: ±1.28 * σ_daily * sqrt(t) * last_close
        sigma = _daily_return_sigma(hist_closes)
        pred_close = main_pred["close"].values.astype(float)
        t_steps = np.arange(1, len(pred_close) + 1, dtype=float)
        half = last_close * 1.28 * sigma * np.sqrt(t_steps)
        low_close = pred_close - half
        high_close = pred_close + half
        low_df = pd.DataFrame({"timestamps": future_dates[:len(low_close)], "close": low_close})
        high_df = pd.DataFrame({"timestamps": future_dates[:len(high_close)], "close": high_close})
        mean_df = pd.DataFrame({"timestamps": future_dates[:len(pred_close)], "close": pred_close.copy()})
        if last_close > 0:
            uncertainty_pct = float((high_close[-1] - low_close[-1]) / last_close * 100.0)

    result = {
        "pred_df": main_pred,
        "mean_df": mean_df,
        "low_df": low_df,
        "high_df": high_df,
        "all_runs": runs,
        "lookback_used": lookback,
        "n_runs": len(runs),
        "context_start": x_timestamp.iloc[0],
        "forecast_start": last_date,
        "uncertainty_pct": round(float(uncertainty_pct), 4),
    }
    forecast_cache.set(cache_key, result)
    return result
