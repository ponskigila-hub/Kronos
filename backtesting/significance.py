"""Paired forecast-loss tests with conservative small-sample handling."""
import numpy as np
from scipy import stats


def diebold_mariano_test(errors_a, errors_b, h=1, power=2, min_origins=20):
    """Compare paired origin-level losses (A-B); positive means A is worse.

    ``h`` is overlap in forecast origins, not bars. Small samples are
    reported as insufficient rather than assigned a misleading p-value.
    """
    a, b = np.asarray(errors_a, dtype=float), np.asarray(errors_b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    n, overlap = len(a), max(1, int(h))
    if n < min_origins or n <= overlap + 1:
        return {"dm_stat": np.nan, "p_value": np.nan, "better_model": "unknown",
                "n_origins": n, "note": f"insufficient independent forecast origins ({n}; need at least {min_origins})"}
    d = np.abs(a) ** power - np.abs(b) ** power
    d_mean = float(np.mean(d))
    centered = d - d_mean
    long_run_var = float(np.dot(centered, centered) / n)
    for lag in range(1, min(overlap, n - 1)):
        cov = float(np.dot(centered[lag:], centered[:-lag]) / n)
        long_run_var += 2 * (1 - lag / overlap) * cov
    if not np.isfinite(long_run_var) or long_run_var <= 0:
        return {"dm_stat": np.nan, "p_value": np.nan, "better_model": "tie",
                "n_origins": n, "note": "loss differential has no reliable positive long-run variance"}
    dm = d_mean / np.sqrt(long_run_var / n)
    correction_sq = (n + 1 - 2 * overlap + overlap * (overlap - 1) / n) / n
    if correction_sq <= 0:
        return {"dm_stat": np.nan, "p_value": np.nan, "better_model": "unknown",
                "n_origins": n, "note": "insufficient sample size for the HLN correction"}
    dm *= np.sqrt(correction_sq)
    p = float(2 * stats.t.sf(abs(dm), df=n - 1))
    better = "B" if d_mean > 0 else "A" if d_mean < 0 else "tie"
    return {"dm_stat": float(dm), "p_value": p, "better_model": better,
            "n_origins": n, "mean_loss_difference_a_minus_b": d_mean,
            "note": "paired origin-level DM test; p-value is unadjusted for other research choices"}


def compare_models_dm(horizon_df_a, horizon_df_b, h=1, step_size=None, min_origins=20):
    """Align one endpoint forecast per split origin and run paired DM."""
    if horizon_df_a.empty or horizon_df_b.empty:
        return {"dm_stat": np.nan, "p_value": np.nan, "better_model": "unknown",
                "n_origins": 0, "note": "no paired forecasts"}
    keys = ["split_date"] if "split_date" in horizon_df_a and "split_date" in horizon_df_b else ["date"]
    merged = horizon_df_a.merge(horizon_df_b, on=keys, suffixes=("_a", "_b"))
    if merged.empty:
        return {"dm_stat": np.nan, "p_value": np.nan, "better_model": "unknown",
                "n_origins": 0, "note": "no paired forecasts on common origins"}
    step = max(1, int(step_size or h))
    overlap = max(1, int(np.ceil(float(h) / step)))
    actual_col = "actual_return" if "actual_return_a" in merged and "actual_return_b" in merged else "actual"
    predicted_col = "predicted_return" if "predicted_return_a" in merged and "predicted_return_b" in merged else "predicted"
    result = diebold_mariano_test(
        merged[f"{actual_col}_a"].values - merged[f"{predicted_col}_a"].values,
        merged[f"{actual_col}_b"].values - merged[f"{predicted_col}_b"].values,
        h=overlap, min_origins=min_origins)
    result["n_origins"] = len(merged)
    result["origin_overlap_lags"] = overlap
    return result


def holm_adjust(p_values):
    """Holm step-down family-wise correction; NaNs remain NaN."""
    vals = np.asarray(p_values, dtype=float)
    out = np.full(vals.shape, np.nan, dtype=float)
    valid = np.flatnonzero(np.isfinite(vals))
    if not len(valid):
        return out
    order = valid[np.argsort(vals[valid])]
    m = len(order)
    adjusted = np.maximum.accumulate([(m - i) * vals[idx] for i, idx in enumerate(order)])
    for idx, value in zip(order, adjusted):
        out[idx] = min(1.0, float(value))
    return out
