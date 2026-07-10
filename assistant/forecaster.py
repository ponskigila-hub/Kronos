"""
Wraps KronosPredictor.predict() with:
  - automatic future-date generation
  - optional multi-run sampling to build a confidence band (since a single
    predict() call already averages `sample_count` internal samples into
    one deterministic path, we run predict() N independent times to see
    the spread across runs)
"""
import numpy as np
import pandas as pd

from .model_loader import get_predictor
from .config import DEFAULT_PRED_LEN, DEFAULT_SAMPLE_RUNS

FEATURE_COLS = ["open", "high", "low", "close", "volume", "amount"]


def _future_dates(last_date, pred_len):
    return pd.date_range(start=last_date + pd.offsets.BDay(1), periods=pred_len, freq="B")


def run_forecast(hist_df, pred_len=None, n_runs=None, lookback=None, T=1.0, top_p=0.9):
    """
    hist_df: cleaned history from assistant.data_fetcher.fetch_history
             (must contain 'timestamps' + FEATURE_COLS)
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
    predictor = get_predictor()

    lookback = lookback or min(predictor.max_context, len(hist_df))
    lookback = min(lookback, len(hist_df))

    x_df = hist_df.iloc[-lookback:][FEATURE_COLS].copy()
    x_timestamp = hist_df.iloc[-lookback:]["timestamps"].copy()
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
            sample_count=1,
            verbose=False,
        )
        pred_df = pred_df.iloc[:pred_len].copy()
        pred_df["timestamps"] = future_dates[: len(pred_df)]
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
