"""
Wraps assistant.forecaster.run_forecast so Kronos can be plugged into
WalkForwardValidator.run() as a `predict_fn(train_df, horizon) -> np.array`,
exactly like every benchmark function in backtesting/benchmarks.py.
"""
import numpy as np

from assistant.forecaster import run_forecast


def make_kronos_predict_fn(lookback=None, T=1.0, top_p=0.9, n_runs=1):
    """
    Returns a predict_fn closure with fixed Kronos hyperparameters -- used
    directly by hyperparam_search.py to evaluate different settings.
    """
    def predict_fn(train_df, horizon):
        fc = run_forecast(
            train_df, pred_len=horizon, n_runs=n_runs,
            lookback=lookback, T=T, top_p=top_p,
        )
        return fc["pred_df"]["close"].values

    predict_fn.name = "Kronos"
    predict_fn.params = {"lookback": lookback, "T": T, "top_p": top_p, "n_runs": n_runs}
    return predict_fn
