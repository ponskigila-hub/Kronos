"""
Correlation matrix across a user's watchlist -- shows which tickers move
together (useful for spotting hidden concentration/lack of diversification).
No Kronos calls -- just historical price data + pandas .corr().
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import data_fetcher
from .config import CHARTS_DIR


def compute_correlation_matrix(tickers, lookback_days=90):
    """
    tickers: list of ticker symbols (e.g. a user's watchlist).
    Returns (corr_df, failed_tickers). corr_df is a DataFrame of pairwise
    correlations of daily returns; failed_tickers lists any that couldn't
    be fetched.
    """
    closes = {}
    failed = []
    for t in tickers:
        try:
            hist = data_fetcher.fetch_history(t, lookback_days=lookback_days)
            closes[t] = hist.set_index("timestamps")["close"]
        except data_fetcher.TickerNotFoundError:
            failed.append(t)

    if len(closes) < 2:
        return None, failed

    price_df = pd.DataFrame(closes).dropna(how="all")
    returns_df = price_df.pct_change().dropna(how="all")
    corr_df = returns_df.corr()
    return corr_df, failed


def format_correlation_text(corr_df):
    if corr_df is None or corr_df.empty:
        return "Need at least 2 valid tickers with overlapping history to compute correlations."

    pairs = []
    tickers = list(corr_df.columns)
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            pairs.append((tickers[i], tickers[j], corr_df.iloc[i, j]))
    pairs.sort(key=lambda p: abs(p[2]), reverse=True)

    lines = ["Correlation of daily returns (1.0 = always move together, -1.0 = always move opposite):"]
    for a, b, corr in pairs[:8]:
        label = "highly correlated" if corr > 0.7 else "inversely correlated" if corr < -0.3 else "loosely correlated"
        lines.append(f"  {a} - {b}: {corr:+.2f} ({label})")

    highest = pairs[0] if pairs else None
    if highest and highest[2] > 0.7:
        lines.append(f"\n{highest[0]} and {highest[1]} tend to move together strongly -- "
                      f"holding both adds less diversification than it might seem.")
    return "\n".join(lines)


def build_correlation_heatmap(corr_df, save_path=None):
    if corr_df is None or corr_df.empty:
        return None
    n = len(corr_df)
    fig, ax = plt.subplots(figsize=(max(5, n * 0.9), max(4, n * 0.8)))
    im = ax.imshow(corr_df.values, cmap="RdYlGn", vmin=-1, vmax=1)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(corr_df.columns, rotation=45, ha="right")
    ax.set_yticklabels(corr_df.columns)
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{corr_df.values[i, j]:.2f}", ha="center", va="center",
                     color="black" if abs(corr_df.values[i, j]) < 0.6 else "white", fontsize=9)
    fig.colorbar(im, ax=ax, label="Correlation")
    ax.set_title("Watchlist Correlation Matrix (daily returns)")
    fig.tight_layout()

    if save_path is None:
        save_path = os.path.join(CHARTS_DIR, "watchlist_correlation.png")
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    return save_path
