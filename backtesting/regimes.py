"""
Requirement #9: robustness testing across market regimes. Classifies each
bar into a trend regime (bull/bear/sideways) and a volatility regime
(high/low), then lets you split walk-forward results by regime to see
whether Kronos's accuracy holds up outside "easy" market conditions.
"""
import numpy as np
import pandas as pd


def classify_regimes(df, trend_window=60, vol_window=20, trend_threshold=0.05,
                      price_col="close"):
    """
    df: DataFrame with 'timestamps' and price_col, sorted ascending.
    Adds two columns:
      - trend_regime: "bull" / "bear" / "sideways", based on the
        trend_window-day % change vs. trend_threshold (default +/-5%)
      - vol_regime: "high" / "low", based on whether rolling volatility
        (std of daily returns over vol_window) is above/below its own
        median for the series
    Returns a copy of df with these columns added.
    """
    out = df.copy()
    returns = out[price_col].pct_change()

    trend_pct = out[price_col].pct_change(periods=trend_window)
    out["trend_regime"] = np.select(
        [trend_pct > trend_threshold, trend_pct < -trend_threshold],
        ["bull", "bear"],
        default="sideways",
    )

    rolling_vol = returns.rolling(vol_window).std()
    vol_median = rolling_vol.median()
    out["vol_regime"] = np.where(rolling_vol >= vol_median, "high", "low")
    out.loc[rolling_vol.isna(), "vol_regime"] = "unknown"
    out.loc[trend_pct.isna(), "trend_regime"] = "unknown"

    return out


def split_by_regime(horizon_df, regime_df, regime_col="trend_regime", date_col="date"):
    """
    horizon_df: per-horizon walk-forward results (has 'date' per prediction).
    regime_df: output of classify_regimes (has 'timestamps' and the regime
               columns), typically the same df the walk-forward ran on.
    Returns {regime_label: sub-DataFrame of horizon_df} so you can run
    metrics.compute_all_metrics() on each slice separately.
    """
    lookup = regime_df.set_index("timestamps")[regime_col]
    merged = horizon_df.copy()
    merged["_regime"] = merged[date_col].map(lookup)

    groups = {}
    for label, group in merged.groupby("_regime"):
        groups[label] = group.drop(columns=["_regime"])
    return groups
