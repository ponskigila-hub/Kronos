"""
Requirement #8: residual analysis. Uses scipy for the normality test and
statsmodels for the autocorrelation/heteroscedasticity tests (both already
in requirements.txt after this update). Every function degrades gracefully
(returns NaN + a note) instead of crashing if a package is missing or a
test's assumptions aren't met (e.g. Shapiro-Wilk needs 3-5000 samples).
"""
import numpy as np
from scipy import stats


def residuals_from_df(df):
    """df: the per-horizon walk-forward DataFrame (actual/predicted cols)."""
    return (df["predicted"] - df["actual"]).values


def bias(residuals):
    return float(np.mean(residuals))


def shapiro_wilk_normality(residuals):
    """H0: residuals are normally distributed. Low p-value => reject
    normality."""
    residuals = np.asarray(residuals)
    residuals = residuals[~np.isnan(residuals)]
    if not (3 <= len(residuals) <= 5000):
        return {"statistic": np.nan, "p_value": np.nan,
                "note": "Shapiro-Wilk requires 3-5000 samples"}
    stat, p = stats.shapiro(residuals)
    return {"statistic": float(stat), "p_value": float(p),
            "note": "normal" if p > 0.05 else "not normal (reject H0 at 5%)"}


def durbin_watson_autocorrelation(residuals):
    """~2.0 = no autocorrelation; <2 = positive autocorrelation; >2 =
    negative autocorrelation."""
    try:
        from statsmodels.stats.stattools import durbin_watson
    except ImportError:
        return {"statistic": np.nan, "note": "statsmodels not installed"}
    residuals = np.asarray(residuals)
    residuals = residuals[~np.isnan(residuals)]
    if len(residuals) < 2:
        return {"statistic": np.nan, "note": "not enough data"}
    stat = durbin_watson(residuals)
    note = "no significant autocorrelation" if 1.5 < stat < 2.5 else "autocorrelation present"
    return {"statistic": float(stat), "note": note}


def ljung_box_autocorrelation(residuals, lags=10):
    """H0: residuals are independently distributed (no autocorrelation up
    to `lags`). Low p-value => reject independence."""
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox
    except ImportError:
        return {"statistic": np.nan, "p_value": np.nan, "note": "statsmodels not installed"}
    residuals = np.asarray(residuals)
    residuals = residuals[~np.isnan(residuals)]
    lags = min(lags, max(1, len(residuals) // 2 - 1))
    if len(residuals) < 8:
        return {"statistic": np.nan, "p_value": np.nan, "note": "not enough data"}
    result = acorr_ljungbox(residuals, lags=[lags], return_df=True)
    stat = float(result["lb_stat"].iloc[0])
    p = float(result["lb_pvalue"].iloc[0])
    return {"statistic": stat, "p_value": p,
            "note": "independent" if p > 0.05 else "autocorrelation present (reject H0 at 5%)"}


def breusch_pagan_heteroscedasticity(residuals, fitted_values):
    """H0: residual variance is constant (homoscedastic). Low p-value =>
    reject homoscedasticity (i.e. variance changes with the predicted level)."""
    try:
        from statsmodels.stats.diagnostic import het_breuschpagan
        import statsmodels.api as sm
    except ImportError:
        return {"statistic": np.nan, "p_value": np.nan, "note": "statsmodels not installed"}
    residuals = np.asarray(residuals)
    fitted_values = np.asarray(fitted_values)
    mask = ~(np.isnan(residuals) | np.isnan(fitted_values))
    residuals, fitted_values = residuals[mask], fitted_values[mask]
    if len(residuals) < 10:
        return {"statistic": np.nan, "p_value": np.nan, "note": "not enough data"}
    exog = sm.add_constant(fitted_values)
    stat, p, _, _ = het_breuschpagan(residuals, exog)
    return {"statistic": float(stat), "p_value": float(p),
            "note": "homoscedastic" if p > 0.05 else "heteroscedasticity present (reject H0 at 5%)"}


def analyze_residuals(df):
    """
    df: per-horizon walk-forward DataFrame (needs 'actual' and 'predicted').
    Returns a dict combining every test above, ready to drop into a report.
    """
    residuals = residuals_from_df(df)
    return {
        "bias": bias(residuals),
        "shapiro_wilk": shapiro_wilk_normality(residuals),
        "durbin_watson": durbin_watson_autocorrelation(residuals),
        "ljung_box": ljung_box_autocorrelation(residuals),
        "breusch_pagan": breusch_pagan_heteroscedasticity(residuals, df["predicted"].values),
    }
