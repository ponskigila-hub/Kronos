"""
Statistical significance testing for model comparisons -- answers "is Kronos
actually better than this benchmark, or is the RMSE gap just noise?" This
costs zero extra Kronos calls: it only reuses predictions the walk-forward
run already made, so it's essentially free to compute even on an 8GB laptop
with no GPU.
"""
import numpy as np
from scipy import stats


def diebold_mariano_test(errors_a, errors_b, h=1, power=2):
    """
    Diebold-Mariano test comparing two forecasts' loss series.

    errors_a, errors_b: arrays of (actual - predicted) for model A and
                         model B respectively, aligned on the same dates.
    h: forecast horizon the errors came from (used for the
       Harvey-Leybourne-Newbold small-sample correction).
    power: 1 = compare mean absolute error, 2 = compare mean squared error
           (default, most common).

    Returns {"dm_stat": float, "p_value": float, "better_model": "A"|"B"|"tie",
             "note": str}. A significant result (p < 0.05) with better_model
    telling you which one actually had lower loss -- not significant means
    "can't tell them apart with this much data."
    """
    errors_a = np.asarray(errors_a, dtype=float)
    errors_b = np.asarray(errors_b, dtype=float)
    mask = ~(np.isnan(errors_a) | np.isnan(errors_b))
    errors_a, errors_b = errors_a[mask], errors_b[mask]
    n = len(errors_a)

    if n < 10:
        return {"dm_stat": np.nan, "p_value": np.nan, "better_model": "tie",
                "note": f"only {n} paired predictions -- not enough for a reliable DM test (need 10+)"}

    loss_a = np.abs(errors_a) ** power
    loss_b = np.abs(errors_b) ** power
    d = loss_a - loss_b  # d > 0 on average => model A worse than model B

    d_mean = np.mean(d)
    # Newey-West-style long-run variance estimate, accounting for the
    # autocorrelation h-step-ahead errors have by construction.
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0
    for lag in range(1, h):
        if lag >= n:
            break
        cov = np.cov(d[lag:], d[:-lag])[0, 1] if n - lag > 1 else 0.0
        var_d += 2 * (1 - lag / h) * cov
    var_d = max(var_d, 1e-12) / n

    dm_stat = d_mean / np.sqrt(var_d)

    # Harvey, Leybourne & Newbold (1997) small-sample correction
    correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_stat *= correction

    p_value = float(2 * (1 - stats.t.cdf(np.abs(dm_stat), df=n - 1)))

    if p_value < 0.05:
        better_model = "B" if d_mean > 0 else "A"
        note = f"statistically significant difference (p={p_value:.3f}) -- model {better_model} has lower error"
    else:
        better_model = "tie"
        note = f"not statistically significant (p={p_value:.3f}) -- can't confidently say one model is better"

    return {"dm_stat": float(dm_stat), "p_value": p_value, "better_model": better_model, "note": note}


def compare_models_dm(horizon_df_a, horizon_df_b, h=1):
    """
    Convenience wrapper: takes two per-horizon walk-forward DataFrames
    (each with 'date', 'actual', 'predicted') for the SAME dates, aligns
    them, and runs the DM test on their errors.
    """
    merged = horizon_df_a.merge(horizon_df_b, on="date", suffixes=("_a", "_b"))
    if merged.empty:
        return {"dm_stat": np.nan, "p_value": np.nan, "better_model": "tie",
                "note": "no overlapping predictions between the two models to compare"}
    errors_a = merged["actual_a"].values - merged["predicted_a"].values
    errors_b = merged["actual_b"].values - merged["predicted_b"].values
    return diebold_mariano_test(errors_a, errors_b, h=h)
