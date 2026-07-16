"""
Requirement #3: every metric group requested -- regression, forecast bias,
directional, correlation, and financial (hit ratio, information coefficient).

All functions take numpy arrays / pandas Series of equal length and are
pure (no side effects), so they're easy to unit test and reuse in the
walk-forward loop, regime splitting, and hyperparameter search.
"""
import numpy as np
from scipy import stats


def _clean(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    return y_true[mask], y_pred[mask]


# ---------------------------------------------------------------------------
# Regression metrics
# ---------------------------------------------------------------------------
def mae(y_true, y_pred):
    y_true, y_pred = _clean(y_true, y_pred)
    return float(np.mean(np.abs(y_true - y_pred))) if len(y_true) else np.nan


def mse(y_true, y_pred):
    y_true, y_pred = _clean(y_true, y_pred)
    return float(np.mean((y_true - y_pred) ** 2)) if len(y_true) else np.nan


def rmse(y_true, y_pred):
    m = mse(y_true, y_pred)
    return float(np.sqrt(m)) if not np.isnan(m) else np.nan


def mape(y_true, y_pred):
    y_true, y_pred = _clean(y_true, y_pred)
    nonzero = y_true != 0
    if not nonzero.any():
        return np.nan
    return float(np.mean(np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero])) * 100)


def smape(y_true, y_pred):
    y_true, y_pred = _clean(y_true, y_pred)
    denom = (np.abs(y_true) + np.abs(y_pred))
    nonzero = denom != 0
    if not nonzero.any():
        return np.nan
    return float(np.mean(2 * np.abs(y_pred[nonzero] - y_true[nonzero]) / denom[nonzero]) * 100)


def rmsle(y_true, y_pred):
    y_true, y_pred = _clean(y_true, y_pred)
    valid = (y_true > 0) & (y_pred > 0)
    if not valid.any():
        return np.nan  # not meaningful for negative/zero prices
    return float(np.sqrt(np.mean((np.log1p(y_pred[valid]) - np.log1p(y_true[valid])) ** 2)))


# ---------------------------------------------------------------------------
# Forecast bias metrics
# ---------------------------------------------------------------------------
def mean_forecast_error(y_true, y_pred):
    """Signed bias: positive = model over-predicts on average."""
    y_true, y_pred = _clean(y_true, y_pred)
    return float(np.mean(y_pred - y_true)) if len(y_true) else np.nan


def median_absolute_error(y_true, y_pred):
    y_true, y_pred = _clean(y_true, y_pred)
    return float(np.median(np.abs(y_true - y_pred))) if len(y_true) else np.nan


# ---------------------------------------------------------------------------
# Directional metrics
# ---------------------------------------------------------------------------
def direction_accuracy(y_true, y_pred, y_prev):
    """% of predictions that got the direction (up/down/flat) right, using
    the last known actual price (`y_prev`) as the reference point."""
    y_true, y_pred = _clean(y_true, y_pred)
    y_prev = np.asarray(y_prev, dtype=float)[:len(y_true)]
    actual_dir = np.sign(y_true - y_prev)
    pred_dir = np.sign(y_pred - y_prev)
    if len(actual_dir) == 0:
        return np.nan
    return float(np.mean(actual_dir == pred_dir) * 100)


def up_down_accuracy(y_true, y_pred, y_prev):
    """Direction accuracy split by whether the actual move was up or down."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    y_prev = np.asarray(y_prev, dtype=float)
    actual_dir = np.sign(y_true - y_prev)
    pred_dir = np.sign(y_pred - y_prev)

    up_mask = actual_dir > 0
    down_mask = actual_dir < 0
    up_acc = float(np.mean(pred_dir[up_mask] == 1) * 100) if up_mask.any() else np.nan
    down_acc = float(np.mean(pred_dir[down_mask] == -1) * 100) if down_mask.any() else np.nan
    return {"up_accuracy": up_acc, "down_accuracy": down_acc}


# ---------------------------------------------------------------------------
# Correlation metrics
# ---------------------------------------------------------------------------
def pearson_correlation(y_true, y_pred):
    y_true, y_pred = _clean(y_true, y_pred)
    if len(y_true) < 2 or np.std(y_true) == 0 or np.std(y_pred) == 0:
        return np.nan
    return float(stats.pearsonr(y_true, y_pred)[0])


def spearman_correlation(y_true, y_pred):
    y_true, y_pred = _clean(y_true, y_pred)
    if len(y_true) < 2 or np.std(y_true) == 0 or np.std(y_pred) == 0:
        return np.nan
    return float(stats.spearmanr(y_true, y_pred)[0])


# ---------------------------------------------------------------------------
# Financial metrics
# ---------------------------------------------------------------------------
def hit_ratio(y_true, y_pred, y_prev):
    """Same idea as direction_accuracy, kept as a separate name since it's
    the standard term in a trading context (fraction of correctly called
    up/down moves)."""
    return direction_accuracy(y_true, y_pred, y_prev)


def information_coefficient(y_true, y_pred, y_prev):
    """Rank correlation (Spearman) between predicted returns and realized
    returns -- the standard quant definition of IC."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    y_prev = np.asarray(y_prev, dtype=float)
    actual_ret = (y_true - y_prev) / y_prev
    pred_ret = (y_pred - y_prev) / y_prev
    return spearman_correlation(actual_ret, pred_ret)


# ---------------------------------------------------------------------------
# Convenience: compute everything at once
# ---------------------------------------------------------------------------
def compute_all_metrics(df):
    """
    df: DataFrame with columns ['actual', 'predicted', 'prev_actual'] --
    exactly what WalkForwardValidator.run() produces per horizon.
    Returns a flat dict of every metric above.
    """
    y_true, y_pred, y_prev = df["actual"].values, df["predicted"].values, df["prev_actual"].values
    updown = up_down_accuracy(y_true, y_pred, y_prev)
    pred_dir = np.sign(y_pred - y_prev)
    actual_dir = np.sign(y_true - y_prev)
    n = len(df)

    metrics_dict = {
        "n_predictions": int(n),
        "mae": mae(y_true, y_pred),
        "mse": mse(y_true, y_pred),
        "rmse": rmse(y_true, y_pred),
        "mape": mape(y_true, y_pred),
        "smape": smape(y_true, y_pred),
        "rmsle": rmsle(y_true, y_pred),
        "mean_forecast_error": mean_forecast_error(y_true, y_pred),
        "median_absolute_error": median_absolute_error(y_true, y_pred),
        "direction_accuracy": direction_accuracy(y_true, y_pred, y_prev),
        "up_accuracy": updown["up_accuracy"],
        "down_accuracy": updown["down_accuracy"],
        "pearson_corr": pearson_correlation(y_true, y_pred),
        "spearman_corr": spearman_correlation(y_true, y_pred),
        "hit_ratio": hit_ratio(y_true, y_pred, y_prev),
        "information_coefficient": information_coefficient(y_true, y_pred, y_prev),
        "pred_up_fraction": float(np.mean(pred_dir == 1) * 100) if n else np.nan,
        "actual_up_fraction": float(np.mean(actual_dir == 1) * 100) if n else np.nan,
    }
    metrics_dict.update(reliability_flags(metrics_dict))
    return metrics_dict


def reliability_flags(metrics_dict, min_reliable_n=30, bias_threshold=90.0):
    """
    Sanity checks so a headline accuracy/RMSE number doesn't get trusted
    when it shouldn't be:
      - low_sample_warning: True if there aren't enough predictions for the
        accuracy figure to be statistically meaningful (rule of thumb: 30+).
      - direction_bias_warning: True if the model predicted the same
        direction (up or down) on more than `bias_threshold`% of
        predictions -- in that case, "direction accuracy" mostly reflects
        the market's own base rate, not real forecasting skill.
    """
    n = metrics_dict.get("n_predictions", 0)
    pred_up = metrics_dict.get("pred_up_fraction", np.nan)

    low_sample = n < min_reliable_n
    biased = (pred_up == pred_up) and (pred_up >= bias_threshold or pred_up <= 100 - bias_threshold)

    notes = []
    if low_sample:
        # rough 95% CI half-width for a proportion, informative even if the
        # metric in question isn't itself a proportion
        acc = metrics_dict.get("direction_accuracy", np.nan)
        if acc == acc and n > 0:
            p = acc / 100
            half_width = 1.96 * (p * (1 - p) / n) ** 0.5 * 100
            notes.append(f"only {n} predictions -- direction accuracy could plausibly be "
                          f"anywhere from {max(0, acc - half_width):.0f}% to {min(100, acc + half_width):.0f}%")
        else:
            notes.append(f"only {n} predictions -- not enough to draw conclusions")
    if biased:
        direction = "UP" if pred_up >= bias_threshold else "DOWN"
        notes.append(f"model predicted {direction} on {pred_up if direction == 'UP' else 100 - pred_up:.0f}% "
                      f"of predictions -- accuracy mostly reflects the market's own base rate here, "
                      f"not real directional skill")

    return {
        "low_sample_warning": bool(low_sample),
        "direction_bias_warning": bool(biased),
        "reliability_notes": notes,
    }
