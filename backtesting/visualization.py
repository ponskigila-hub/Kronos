"""
Requirement #7: visualization suite. Every function saves a PNG and returns
the file path, so backtesting/runner.py can call these in a loop and collect
paths for the final report without holding many figures in memory at once.
"""
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_actual_vs_predicted(horizon_df, title, save_path):
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(horizon_df["date"], horizon_df["actual"], label="Actual", linewidth=1.3)
    ax.scatter(horizon_df["date"], horizon_df["predicted"], label="Predicted",
               s=10, color="#ff7f0e", alpha=0.6)
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Price")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.xticks(rotation=45)
    return _save(fig, save_path)


def plot_prediction_error(horizon_df, title, save_path):
    error = horizon_df["predicted"] - horizon_df["actual"]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(horizon_df["date"], error, color="crimson", linewidth=1)
    ax.axhline(0, color="gray", linestyle=":")
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Prediction error (predicted - actual)")
    ax.grid(alpha=0.3)
    plt.xticks(rotation=45)
    return _save(fig, save_path)


def plot_residual_distribution(horizon_df, title, save_path):
    residuals = horizon_df["predicted"] - horizon_df["actual"]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.hist(residuals, bins=30, color="#1f77b4", alpha=0.8, edgecolor="white")
    ax.axvline(residuals.mean(), color="crimson", linestyle="--", label=f"mean={residuals.mean():.3f}")
    ax.set_title(title)
    ax.set_xlabel("Residual")
    ax.set_ylabel("Frequency")
    ax.legend()
    return _save(fig, save_path)


def plot_qq(horizon_df, title, save_path):
    residuals = (horizon_df["predicted"] - horizon_df["actual"]).values
    fig, ax = plt.subplots(figsize=(7, 7))
    stats.probplot(residuals, dist="norm", plot=ax)
    ax.set_title(title)
    return _save(fig, save_path)


def plot_residual_autocorrelation(horizon_df, title, save_path, max_lag=20):
    residuals = (horizon_df["predicted"] - horizon_df["actual"]).values
    residuals = residuals[~np.isnan(residuals)]
    n = len(residuals)
    lags = range(1, min(max_lag, n - 1) + 1)
    acf_vals = [np.corrcoef(residuals[:-lag], residuals[lag:])[0, 1] for lag in lags]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.stem(list(lags), acf_vals)
    ci = 1.96 / np.sqrt(n)
    ax.axhline(ci, color="gray", linestyle="--", linewidth=0.8)
    ax.axhline(-ci, color="gray", linestyle="--", linewidth=0.8)
    ax.set_title(title)
    ax.set_xlabel("Lag")
    ax.set_ylabel("Autocorrelation")
    return _save(fig, save_path)


def plot_confidence_interval(horizon_df, title, save_path, low_col=None, high_col=None):
    """If your horizon_df has low/high confidence-band columns (from
    multi-run Kronos forecasts), plot them; otherwise just plot actual vs
    predicted."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(horizon_df["date"], horizon_df["actual"], label="Actual", linewidth=1.3)
    ax.plot(horizon_df["date"], horizon_df["predicted"], label="Predicted",
            linewidth=1.3, linestyle="--", color="#ff7f0e")
    if low_col and high_col and low_col in horizon_df and high_col in horizon_df:
        ax.fill_between(horizon_df["date"], horizon_df[low_col], horizon_df[high_col],
                         color="#ff7f0e", alpha=0.15, label="Confidence range")
    ax.set_title(title)
    ax.legend()
    ax.grid(alpha=0.3)
    plt.xticks(rotation=45)
    return _save(fig, save_path)


def plot_horizon_comparison(metrics_by_horizon, metric_name, title, save_path):
    """metrics_by_horizon: {horizon: metrics_dict} from compute_all_metrics."""
    horizons = sorted(metrics_by_horizon.keys())
    values = [metrics_by_horizon[h].get(metric_name, np.nan) for h in horizons]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(horizons, values, marker="o")
    ax.set_title(title)
    ax.set_xlabel("Forecast horizon (days)")
    ax.set_ylabel(metric_name)
    ax.grid(alpha=0.3)
    return _save(fig, save_path)


def plot_rolling_metric(horizon_df, metric_fn, window, title, ylabel, save_path):
    """metric_fn(sub_df) -> float, applied over a rolling window of
    predictions sorted by date."""
    df = horizon_df.sort_values("date").reset_index(drop=True)
    values = []
    for i in range(window, len(df) + 1):
        sub = df.iloc[i - window:i]
        values.append(metric_fn(sub))
    dates = df["date"].iloc[window - 1:].reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(dates, values, color="#2ca02c")
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    plt.xticks(rotation=45)
    return _save(fig, save_path)


def plot_equity_curve(equity_df, title, save_path, starting_capital=10000.0):
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(equity_df["date"], equity_df["equity"], color="#1f77b4", linewidth=1.5)
    ax.axhline(starting_capital, color="gray", linestyle=":", label="Starting capital")
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Equity")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.xticks(rotation=45)
    return _save(fig, save_path)


def plot_drawdown(equity_df, title, save_path):
    eq = equity_df["equity"].values
    running_max = np.maximum.accumulate(eq)
    drawdown = (eq / running_max - 1) * 100

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.fill_between(equity_df["date"], drawdown, 0, color="crimson", alpha=0.4)
    ax.plot(equity_df["date"], drawdown, color="crimson", linewidth=1)
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(alpha=0.3)
    plt.xticks(rotation=45)
    return _save(fig, save_path)


def plot_monthly_returns_heatmap(equity_df, title, save_path):
    df = equity_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    monthly = df["equity"].resample("ME").last().pct_change().dropna() * 100
    if monthly.empty:
        return None
    table = monthly.to_frame("ret")
    table["year"] = table.index.year
    table["month"] = table.index.month
    pivot = table.pivot(index="year", columns="month", values="ret")
    pivot = pivot.reindex(columns=range(1, 13))

    fig, ax = plt.subplots(figsize=(12, max(3, 0.5 * len(pivot))))
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto", vmin=-10, vmax=10)
    ax.set_xticks(range(12))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_yticks(range(len(pivot)))
    ax.set_yticklabels(pivot.index)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            val = pivot.values[i, j]
            if not np.isnan(val):
                ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="Monthly return (%)")
    ax.set_title(title)
    return _save(fig, save_path)


def plot_direction_confusion_matrix(horizon_df, title, save_path):
    actual_dir = np.sign(horizon_df["actual"] - horizon_df["prev_actual"])
    pred_dir = np.sign(horizon_df["predicted"] - horizon_df["prev_actual"])
    labels = [-1, 0, 1]
    label_names = ["Down", "Flat", "Up"]
    matrix = np.zeros((3, 3), dtype=int)
    for a, p in zip(actual_dir, pred_dir):
        matrix[labels.index(a), labels.index(p)] += 1

    fig, ax = plt.subplots(figsize=(6, 6))
    im = ax.imshow(matrix, cmap="Blues")
    ax.set_xticks(range(3))
    ax.set_yticks(range(3))
    ax.set_xticklabels(label_names)
    ax.set_yticklabels(label_names)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    for i in range(3):
        for j in range(3):
            ax.text(j, i, matrix[i, j], ha="center", va="center",
                    color="white" if matrix[i, j] > matrix.max() / 2 else "black")
    fig.colorbar(im, ax=ax)
    ax.set_title(title)
    return _save(fig, save_path)
