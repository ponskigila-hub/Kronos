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
from .config import DEFAULT_PRED_LEN, DEFAULT_SAMPLE_RUNS, DEFAULT_KRONOS_SAMPLE_COUNT, DEFAULT_KRONOS_T

FEATURE_COLS = ["open", "high", "low", "close", "volume", "amount"]
OHLC_COLS = ["open", "high", "low", "close"]


def _future_dates(last_date, pred_len):
    return pd.date_range(start=last_date + pd.offsets.BDay(1), periods=pred_len, freq="B")


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
          "pred_df": DataFrame[timestamps, open, high, low, close, volume, amount],
          "low_df":  DataFrame or None (10th percentile close, if n_runs > 1),
          "high_df": DataFrame or None (90th percentile close, if n_runs > 1),
          "lookback_used": int,
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
    last_date = hist_df["timestamps"].max()
    future_dates = _future_dates(last_date, pred_len)
    y_timestamp = pd.Series(future_dates)

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
        runs.append(pred_df.reset_index(drop=True))

    main_pred = runs[0]
    low_df = high_df = None

    if len(runs) > 1:
        stacked_close = np.stack([r["close"].values for r in runs], axis=0)
        median_close = np.median(stacked_close, axis=0)
        low_close = np.percentile(stacked_close, 10, axis=0)
        high_close = np.percentile(stacked_close, 90, axis=0)

        main_pred = main_pred.copy()
        main_pred["close"] = median_close

        low_df = pd.DataFrame({"timestamps": future_dates, "close": low_close})
        high_df = pd.DataFrame({"timestamps": future_dates, "close": high_close})

    return {
        "pred_df": main_pred,
        "low_df": low_df,
        "high_df": high_df,
        "lookback_used": lookback,
        "n_runs": len(runs),
    }
