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


def build_forecast_png(ticker, hist_df, forecast_result, save_path=None, display_days=150):
    """
    Static PNG version of the forecast chart, styled like the original
    yahoopredict.py / csvpredict.py output: historical close line, dashed
    predicted line, optional shaded confidence range, saved to disk.
    Returns the file path.
    """
    pred_df = forecast_result["pred_df"]
    low_df = forecast_result.get("low_df")
    high_df = forecast_result.get("high_df")

    display_hist = hist_df.tail(display_days)

    plt.figure(figsize=(14, 7))

    plt.plot(display_hist["timestamps"], display_hist["close"],
              label="Historical", linewidth=1.5, color="#1f77b4")

    if low_df is not None and high_df is not None:
        plt.fill_between(pred_df["timestamps"], low_df["close"], high_df["close"],
                          color="#ff7f0e", alpha=0.15,
                          label=f"Forecast range ({forecast_result.get('n_runs', 1)} runs)")

    plt.plot(pred_df["timestamps"], pred_df["close"], "--",
              linewidth=2, label="Kronos Forecast", color="#ff7f0e")

    plt.axvline(x=display_hist["timestamps"].iloc[-1], linestyle=":", linewidth=1, color="gray")

    plt.title(f"{ticker} Forecast -- Next {len(pred_df)} Trading Days")
    plt.xlabel("Date")
    plt.ylabel("Close Price")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()

    if save_path is None:
        save_path = os.path.join(CHARTS_DIR, f"{ticker}_kronos_prediction.png")
    plt.savefig(save_path, dpi=150)
    plt.close()
    return save_path


def build_comparison_png(ticker_dfs, save_path=None):
    """Static PNG version of the multi-ticker comparison chart (% change
    from the start of the period, same idea as build_comparison_chart)."""
    plt.figure(figsize=(14, 7))
    for ticker, df in ticker_dfs.items():
        base = df["close"].iloc[0]
        norm = (df["close"] / base - 1) * 100
        plt.plot(df["timestamps"], norm, label=ticker, linewidth=1.8)

    plt.title("Relative Performance (%)")
    plt.xlabel("Date")
    plt.ylabel("% change since period start")
    plt.axhline(y=0, linestyle=":", linewidth=1, color="gray")
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
    ), row=1, col=1)

    # --- Moving averages ---
    for col, name, dash in [("sma_20", "SMA 20", "solid"), ("sma_50", "SMA 50", "solid")]:
        if col in ind_df.columns:
            fig.add_trace(go.Scatter(
                x=ind_df["timestamps"], y=ind_df[col], name=name,
                line=dict(width=1, dash=dash), opacity=0.8,
            ), row=1, col=1)

    # --- Bollinger Bands ---
    if "bb_upper" in ind_df.columns:
        fig.add_trace(go.Scatter(x=ind_df["timestamps"], y=ind_df["bb_upper"],
                                  name="BB Upper", line=dict(width=1, color="rgba(150,150,150,0.5)")), row=1, col=1)
        fig.add_trace(go.Scatter(x=ind_df["timestamps"], y=ind_df["bb_lower"],
                                  name="BB Lower", line=dict(width=1, color="rgba(150,150,150,0.5)"),
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
        line=dict(width=2, dash="dash", color="#ff7f0e"),
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
                                  name="Vol SMA 20", line=dict(width=1, color="purple")), row=2, col=1)

    # --- RSI ---
    if "rsi_14" in ind_df.columns:
        fig.add_trace(go.Scatter(x=ind_df["timestamps"], y=ind_df["rsi_14"], name="RSI 14",
                                  line=dict(width=1.5, color="teal")), row=3, col=1)
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
        fig.add_trace(go.Scatter(x=df["timestamps"], y=norm, name=ticker, mode="lines"))
    fig.update_layout(
        title="Relative Performance (%)", template="plotly_white",
        yaxis_title="% change since period start", height=500,
    )
    return fig
