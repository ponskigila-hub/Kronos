"""
Requirement #6: baseline forecasters, all sharing the same predict_fn(train_df,
horizon) -> array signature as backtesting.kronos_adapter.make_kronos_predict_fn,
so they drop straight into WalkForwardValidator.run().

Included, fully working, no extra heavy dependencies:
  - naive_forecast       (flat: repeat last close)
  - drift_forecast        (last close + average historical daily drift)
  - moving_average_forecast (flat: repeat the trailing N-day average)
  - linear_regression_forecast (numpy polyfit trend extrapolation)
  - arima_forecast         (statsmodels, if installed -- optional per the brief)

Explicitly NOT implemented (both marked "(optional)" in the original spec,
and both require a much heavier dependency -- tensorflow/keras for LSTM,
`prophet`/`cmdstanpy` for Prophet -- that would roughly double install size
and time for something optional):
  - lstm_forecast     -> raises NotImplementedError with guidance
  - prophet_forecast  -> raises NotImplementedError with guidance
"""
import numpy as np


def naive_forecast(train_df, horizon, price_col="close"):
    last = float(train_df.iloc[-1][price_col])
    return np.full(horizon, last)


def drift_forecast(train_df, horizon, price_col="close"):
    prices = train_df[price_col].values
    if len(prices) < 2:
        return naive_forecast(train_df, horizon, price_col)
    avg_drift = np.mean(np.diff(prices))
    last = prices[-1]
    return last + avg_drift * np.arange(1, horizon + 1)


def moving_average_forecast(train_df, horizon, window=20, price_col="close"):
    prices = train_df[price_col].values
    window = min(window, len(prices))
    avg = float(np.mean(prices[-window:]))
    return np.full(horizon, avg)


def linear_regression_forecast(train_df, horizon, lookback=60, price_col="close"):
    prices = train_df[price_col].values
    lookback = min(lookback, len(prices))
    y = prices[-lookback:]
    x = np.arange(len(y))
    if len(y) < 2:
        return naive_forecast(train_df, horizon, price_col)
    slope, intercept = np.polyfit(x, y, 1)
    future_x = np.arange(len(y), len(y) + horizon)
    return slope * future_x + intercept


def arima_forecast(train_df, horizon, order=(5, 1, 0), price_col="close"):
    try:
        from statsmodels.tsa.arima.model import ARIMA
    except ImportError:
        raise ImportError(
            "arima_forecast requires statsmodels: pip install statsmodels"
        )
    prices = train_df[price_col].values
    try:
        model = ARIMA(prices, order=order)
        fitted = model.fit()
        forecast = fitted.forecast(steps=horizon)
        return np.asarray(forecast)
    except Exception:
        # ARIMA can fail to converge on some windows (e.g. too little data,
        # non-stationary edge cases) -- fall back to naive rather than
        # crashing the whole walk-forward run.
        return naive_forecast(train_df, horizon, price_col)


def lstm_forecast(train_df, horizon, price_col="close"):
    raise NotImplementedError(
        "LSTM benchmark is optional and not implemented here -- it needs "
        "tensorflow/keras (a large extra dependency) plus a training loop "
        "re-run on every walk-forward window, which is expensive. To add "
        "it: pip install tensorflow, build a small windowed LSTM trained on "
        "train_df[price_col], and return its horizon-step forecast as a "
        "numpy array to match this module's function signature."
    )


def prophet_forecast(train_df, horizon, price_col="close"):
    raise NotImplementedError(
        "Prophet benchmark is optional and not implemented here -- it needs "
        "the `prophet` package (pulls in cmdstanpy/pystan). To add it: "
        "pip install prophet, fit on a two-column df (ds=timestamps, "
        "y=train_df[price_col]), and return `forecast['yhat']` for the next "
        "`horizon` periods as a numpy array."
    )


def get_benchmark_suite(include_arima=True):
    """Returns {name: predict_fn} for every benchmark that's safe to run
    without extra setup. Pass include_arima=False to skip it even if
    statsmodels is installed (ARIMA is noticeably slower than the others)."""
    suite = {
        "Naive (last close)": naive_forecast,
        "Drift": drift_forecast,
        "Moving Average (20d)": moving_average_forecast,
        "Linear Regression": linear_regression_forecast,
    }
    if include_arima:
        try:
            import statsmodels  # noqa: F401
            suite["ARIMA(5,1,0)"] = arima_forecast
        except ImportError:
            pass  # silently skip -- statsmodels not installed
    return suite
