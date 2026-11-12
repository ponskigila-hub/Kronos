"""
Interactive Plotly charts (item #6): candlestick history + Kronos forecast +
confidence band + technical indicators + volume + news markers on the
timeline, all in one figure with stacked subplots.

Also includes matplotlib PNG export (build_forecast_png /
build_comparison_png) that mirrors the plot style from the original
yahoopredict.py / csvpredict.py scripts -- a static image saved to disk,
for anyone who wants "the same picture as before" instead of / alongside
the interactive HTML chart.
"""
import os

import matplotlib
matplotlib.use("Agg")  # headless-safe: never tries to open a GUI window
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .config import CHARTS_DIR


class LazyFigure:
    """
    Defers building an expensive Plotly figure (multi-subplot candlestick +
    indicators + volume + news markers -- see build_forecast_chart) until
    something actually uses it.

    Why: `result["chart"]` from StockAssistant.handle_message() is only
    ever read by chat_cli.py (always) and, as a same-image fallback, by the
    Discord/WhatsApp adapters when a PNG couldn't be produced (in practice
    never, since a PNG is always built first). The web app's JSON API
    (webapp/app.py) never touches it at all. Building the full interactive
    figure on every single forecast/why/history/comparison call was pure
    wasted work for the web app and for Discord/WhatsApp in the normal
    case -- this makes that cost pay-per-use instead of pay-always, with no
    change in behavior for any caller (a LazyFigure behaves like the real
    Plotly Figure for every operation callers actually perform on it:
    truthiness, `.write_html`, `.write_image`, `.show`, attribute access).
    """
    __slots__ = ("_build_fn", "_args", "_kwargs", "_figure")

    def __init__(self, build_fn, *args, **kwargs):
        self._build_fn = build_fn
        self._args = args
        self._kwargs = kwargs
        self._figure = None

    def _resolve(self):
        if self._figure is None:
            self._figure = self._build_fn(*self._args, **self._kwargs)
        return self._figure

    def __getattr__(self, name):
        return getattr(self._resolve(), name)

    def __bool__(self):
        # A LazyFigure always represents "a chart is available" -- callers
        # use `result.get("chart") is not None` to check for presence, so
        # this only matters if something explicitly does `if fig:`.
        return True


def build_forecast_png(ticker, hist_df, forecast_result, save_path=None, display_days=150, analyst_target=None):
    """
    Modern dark-theme outlook chart inspired by professional valuation /
    range-cone views: historical price, projected centre path, high/low
    band, end-point annotations (Range high / Centre / Low), optional
    analyst consensus target, and a clear "now" vertical.
    """
    pred_df = forecast_result["pred_df"]
    low_df = forecast_result.get("low_df")
    high_df = forecast_result.get("high_df")
    mean_df = forecast_result.get("mean_df")
    n_runs = forecast_result.get("n_runs", 1)

    display_hist = hist_df.tail(display_days)
    forecast_start = forecast_result.get("forecast_start", display_hist["timestamps"].iloc[-1])

    # Prefer mean path when multi-sample available
    centre_df = mean_df if mean_df is not None else pred_df

    fig, ax = plt.subplots(figsize=(14.5, 7.2), facecolor="#0d1117")
    ax.set_facecolor("#0d1117")

    # Historical price (white)
    ax.plot(display_hist["timestamps"], display_hist["close"],
            color="#e6edf3", linewidth=2.0, label="Price", zorder=3)

    # Range band (projected high / low)
    if low_df is not None and high_df is not None:
        ax.fill_between(
            centre_df["timestamps"], low_df["close"], high_df["close"],
            color="#3fb950", alpha=0.12, label="Projected range", zorder=1
        )
        ax.plot(high_df["timestamps"], high_df["close"],
                color="#3fb950", linewidth=1.6, linestyle="--", alpha=0.9, label="Range high", zorder=2)
        ax.plot(low_df["timestamps"], low_df["close"],
                color="#f85149", linewidth=1.6, linestyle="--", alpha=0.9, label="Range low", zorder=2)

    # Centre / mean path
    ax.plot(centre_df["timestamps"], centre_df["close"],
            color="#58a6ff", linewidth=2.6, label="Centre (mean path)", zorder=4)

    # Analyst target (horizontal if provided)
    if analyst_target is not None and analyst_target > 0:
        ax.axhline(analyst_target, color="#bc8cff", linewidth=1.5, linestyle=":",
                   label=f"Analyst target {analyst_target:.2f}", zorder=2)

    # "Now" vertical
    ax.axvline(forecast_start, color="#8b949e", linestyle=":", linewidth=1.4, alpha=0.85, zorder=0)

    # End-point annotations (right side)
    last_x = centre_df["timestamps"].iloc[-1]
    def _annot(y, color, label, offset_y=0):
        ax.annotate(
            f"{label}  {y:.2f}",
            xy=(last_x, y), xytext=(12, offset_y),
            textcoords="offset points",
            color=color, fontsize=9, fontweight="600",
            va="center",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#161b22", edgecolor=color, alpha=0.9),
            arrowprops=dict(arrowstyle="-", color=color, lw=0.8),
        )

    if high_df is not None:
        _annot(float(high_df["close"].iloc[-1]), "#3fb950", "High", 18)
    _annot(float(centre_df["close"].iloc[-1]), "#58a6ff", "Centre", 0)
    if low_df is not None:
        _annot(float(low_df["close"].iloc[-1]), "#f85149", "Low", -18)
    if analyst_target is not None and analyst_target > 0:
        # small purple marker at the right edge height of target
        ax.scatter([last_x], [analyst_target], color="#bc8cff", s=28, zorder=5, marker="D")

    # Styling
    ax.set_title(f"{ticker}  ·  Kronos outlook  ·  next {len(centre_df)} trading days"
                 + (f"  ({n_runs} paths)" if n_runs > 1 else ""),
                 color="#e6edf3", fontsize=13, pad=12, loc="left")
    ax.set_xlabel("")
    ax.set_ylabel("Price", color="#8b949e")
    ax.tick_params(colors="#8b949e", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#30363d")
    ax.grid(True, color="#21262d", alpha=0.7, linewidth=0.6)
    ax.legend(loc="upper left", fontsize=8.5, frameon=True,
              facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3")

    fig.autofmt_xdate(rotation=25)
    fig.tight_layout()

    if save_path is None:
        save_path = os.path.join(CHARTS_DIR, f"{ticker}_kronos_prediction.png")
    fig.savefig(save_path, dpi=160, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return save_path


def build_detailed_forecast_png(ticker, hist_df, forecast_result, save_path=None, display_days=150, analyst_target=None):
    """
    Detailed multi-path outlook (dark range-cone style). Shows individual
    sampled paths faintly, the mean centre, high/low band, end annotations,
    and optional analyst target. Preferred when n_runs > 1.
    """
    # Re-use the polished single-view builder for consistent styling;
    # individual paths are still drawn when present.
    pred_df = forecast_result["pred_df"]
    all_runs = forecast_result.get("all_runs") or [pred_df]
    low_df = forecast_result.get("low_df")
    high_df = forecast_result.get("high_df")
    mean_df = forecast_result.get("mean_df")
    n_runs = forecast_result.get("n_runs", len(all_runs))
    forecast_start = forecast_result.get("forecast_start", hist_df["timestamps"].iloc[-1])

    display_hist = hist_df.tail(display_days)
    centre_df = mean_df if mean_df is not None else pred_df

    fig, ax = plt.subplots(figsize=(14.5, 7.2), facecolor="#0d1117")
    ax.set_facecolor("#0d1117")

    ax.plot(display_hist["timestamps"], display_hist["close"],
            color="#e6edf3", linewidth=2.0, label="Price", zorder=3)

    # Faint individual paths
    for i, run in enumerate(all_runs):
        ax.plot(run["timestamps"], run["close"], color="#f0c14b",
                alpha=0.22, linewidth=1.0,
                label="Sample paths" if i == 0 else None, zorder=1)

    if low_df is not None and high_df is not None:
        ax.fill_between(centre_df["timestamps"], low_df["close"], high_df["close"],
                        color="#3fb950", alpha=0.12, label="Projected range", zorder=1)
        ax.plot(high_df["timestamps"], high_df["close"],
                color="#3fb950", linewidth=1.5, linestyle="--", alpha=0.85, label="Range high", zorder=2)
        ax.plot(low_df["timestamps"], low_df["close"],
                color="#f85149", linewidth=1.5, linestyle="--", alpha=0.85, label="Range low", zorder=2)

    ax.plot(centre_df["timestamps"], centre_df["close"],
            color="#58a6ff", linewidth=2.8, label="Centre (mean)", zorder=4)

    if analyst_target is not None and analyst_target > 0:
        ax.axhline(analyst_target, color="#bc8cff", linewidth=1.5, linestyle=":",
                   label=f"Analyst target {analyst_target:.2f}", zorder=2)

    ax.axvline(forecast_start, color="#8b949e", linestyle=":", linewidth=1.4, alpha=0.85)

    last_x = centre_df["timestamps"].iloc[-1]
    def _annot(y, color, label, offset_y=0):
        ax.annotate(
            f"{label}  {y:.2f}",
            xy=(last_x, y), xytext=(12, offset_y),
            textcoords="offset points",
            color=color, fontsize=9, fontweight="600",
            va="center",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#161b22", edgecolor=color, alpha=0.9),
            arrowprops=dict(arrowstyle="-", color=color, lw=0.8),
        )

    if high_df is not None:
        _annot(float(high_df["close"].iloc[-1]), "#3fb950", "High", 18)
    _annot(float(centre_df["close"].iloc[-1]), "#58a6ff", "Centre", 0)
    if low_df is not None:
        _annot(float(low_df["close"].iloc[-1]), "#f85149", "Low", -18)
    if analyst_target is not None and analyst_target > 0:
        ax.scatter([last_x], [analyst_target], color="#bc8cff", s=28, zorder=5, marker="D")

    ax.set_title(
        f"{ticker}  ·  Kronos detailed outlook  ·  {n_runs} sampled paths  ·  next {len(centre_df)} days",
        color="#e6edf3", fontsize=13, pad=12, loc="left"
    )
    ax.set_xlabel("")
    ax.set_ylabel("Price", color="#8b949e")
    ax.tick_params(colors="#8b949e", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#30363d")
    ax.grid(True, color="#21262d", alpha=0.7, linewidth=0.6)
    ax.legend(loc="upper left", fontsize=8.5, frameon=True,
              facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3")

    fig.autofmt_xdate(rotation=25)
    fig.tight_layout()

    if save_path is None:
        save_path = os.path.join(CHARTS_DIR, f"{ticker}_detailed_forecast.png")
    fig.savefig(save_path, dpi=160, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return save_path



def build_comparison_png(ticker_dfs, save_path=None):
    """Static PNG version of the multi-ticker comparison chart (% change
    from the start of the period, same idea as build_comparison_chart)."""
    plt.figure(figsize=(14, 7))
    for ticker, df in ticker_dfs.items():
        base = df["close"].iloc[0]
        norm = (df["close"] / base - 1) * 100
        plt.plot(df["timestamps"], norm, label=ticker, linewidth=2.6)

    plt.title("Relative Performance (%)")
    plt.xlabel("Date")
    plt.ylabel("% change since period start")
    plt.axhline(y=0, linestyle=":", linewidth=1.8, color="gray")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()

    if save_path is None:
        name = "_vs_".join(ticker_dfs.keys())
        save_path = os.path.join(CHARTS_DIR, f"{name}_comparison.png")
    plt.savefig(save_path, dpi=150)
    plt.close()
    return save_path


def build_forecast_chart(ticker, hist_df, ind_df, forecast_result, news_items=None):
    pred_df = forecast_result["pred_df"]
    low_df = forecast_result.get("low_df")
    high_df = forecast_result.get("high_df")

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.55, 0.2, 0.25], vertical_spacing=0.04,
        subplot_titles=(f"{ticker} - Price & Forecast", "Volume", "RSI (14)"),
    )

    # --- Candlestick history ---
    fig.add_trace(go.Candlestick(
        x=hist_df["timestamps"], open=hist_df["open"], high=hist_df["high"],
        low=hist_df["low"], close=hist_df["close"], name="Historical",
        # Explicit (bolder than Plotly's thin default) wick/border width so
        # individual candles stay legible even on a dense, months-long
        # history -- matches the rest of this chart's thicker line weights.
        increasing=dict(line=dict(width=1.6)), decreasing=dict(line=dict(width=1.6)),
    ), row=1, col=1)

    # --- Moving averages ---
    for col, name, dash in [("sma_20", "SMA 20", "solid"), ("sma_50", "SMA 50", "solid")]:
        if col in ind_df.columns:
            fig.add_trace(go.Scatter(
                x=ind_df["timestamps"], y=ind_df[col], name=name,
                line=dict(width=2, dash=dash), opacity=0.9,
            ), row=1, col=1)

    # --- Bollinger Bands ---
    if "bb_upper" in ind_df.columns:
        fig.add_trace(go.Scatter(x=ind_df["timestamps"], y=ind_df["bb_upper"],
                                  name="BB Upper", line=dict(width=1.6, color="rgba(120,120,120,0.7)")), row=1, col=1)
        fig.add_trace(go.Scatter(x=ind_df["timestamps"], y=ind_df["bb_lower"],
                                  name="BB Lower", line=dict(width=1.6, color="rgba(120,120,120,0.7)"),
                                  fill="tonexty", fillcolor="rgba(150,150,150,0.08)"), row=1, col=1)

    # --- Confidence band (if multi-run) ---
    if low_df is not None and high_df is not None:
        fig.add_trace(go.Scatter(
            x=list(high_df["timestamps"]) + list(low_df["timestamps"])[::-1],
            y=list(high_df["close"]) + list(low_df["close"])[::-1],
            fill="toself", fillcolor="rgba(255,127,14,0.15)",
            line=dict(color="rgba(255,255,255,0)"), name="Forecast range", showlegend=True,
        ), row=1, col=1)

    # --- Forecast line ---
    fig.add_trace(go.Scatter(
        x=pred_df["timestamps"], y=pred_df["close"], name="Kronos Forecast",
        line=dict(width=3, dash="dash", color="#ff7f0e"),
    ), row=1, col=1)

    # --- News markers on the price timeline ---
    if news_items:
        color_map = {"positive": "green", "negative": "red", "neutral": "gray"}
        for item in news_items:
            if not item.get("published"):
                continue
            try:
                import pandas as pd
                x_val = pd.to_datetime(item["published"], unit="s", errors="coerce")
                if pd.isna(x_val):
                    x_val = pd.to_datetime(item["published"], errors="coerce")
                if pd.isna(x_val):
                    continue
            except Exception:
                continue
            fig.add_trace(go.Scatter(
                x=[x_val], y=[hist_df["close"].iloc[-1]], mode="markers",
                marker=dict(size=9, color=color_map.get(item["sentiment_label"], "gray"), symbol="star"),
                name="News", showlegend=False,
                hovertext=item["title"], hoverinfo="text+x",
            ), row=1, col=1)

    # --- Volume ---
    fig.add_trace(go.Bar(x=hist_df["timestamps"], y=hist_df["volume"], name="Volume",
                          marker_color="rgba(100,100,200,0.5)"), row=2, col=1)
    if "volume_sma_20" in ind_df.columns:
        fig.add_trace(go.Scatter(x=ind_df["timestamps"], y=ind_df["volume_sma_20"],
                                  name="Vol SMA 20", line=dict(width=2, color="purple")), row=2, col=1)

    # --- RSI ---
    if "rsi_14" in ind_df.columns:
        fig.add_trace(go.Scatter(x=ind_df["timestamps"], y=ind_df["rsi_14"], name="RSI 14",
                                  line=dict(width=2.5, color="teal")), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)

    fig.update_layout(
        height=850, template="plotly_white",
        title=f"{ticker} -- Kronos AI Forecast & Technical Analysis",
        xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02),
    )
    return fig


def build_comparison_chart(ticker_dfs):
    """
    ticker_dfs: {ticker: hist_df} - normalizes each series to % change from
    its first value so different-priced assets are comparable on one chart.
    """
    fig = go.Figure()
    for ticker, df in ticker_dfs.items():
        base = df["close"].iloc[0]
        norm = (df["close"] / base - 1) * 100
        fig.add_trace(go.Scatter(x=df["timestamps"], y=norm, name=ticker, mode="lines", line=dict(width=2.6)))
    fig.update_layout(
        title="Relative Performance (%)", template="plotly_white",
        yaxis_title="% change since period start", height=500,
    )
    return fig
