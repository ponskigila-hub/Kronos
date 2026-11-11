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
              label="Historical", linewidth=2.2, color="#1f77b4")

    if low_df is not None and high_df is not None:
        plt.fill_between(pred_df["timestamps"], low_df["close"], high_df["close"],
                          color="#ff7f0e", alpha=0.15,
                          label=f"Forecast range ({forecast_result.get('n_runs', 1)} runs)")

    plt.plot(pred_df["timestamps"], pred_df["close"], "--",
              linewidth=2.8, label="Kronos Forecast", color="#ff7f0e")

    plt.axvline(x=display_hist["timestamps"].iloc[-1], linestyle=":", linewidth=1.8, color="gray")

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


def build_detailed_forecast_png(ticker, hist_df, forecast_result, save_path=None, display_days=150):
    """
    Detailed "spaghetti plot" forecast chart: full historical close, a
    marker for where the model's context window begins, a marker for
    where the forecast starts, every individual sampled path (thin,
    translucent), the mean forecast across all paths (bold), and a
    10-90th percentile band. Matches the style of Kronos forecast
    visualizations commonly used to sanity-check how much the sampled
    paths actually agree with each other.

    Only meaningfully different from build_forecast_png() when
    forecast_result came from run_forecast(..., n_runs > 1) -- with
    n_runs=1 there's only one path to plot and no band, so prefer
    build_forecast_png() for the fast/default case. This one costs
    n_runs x the Kronos inference time; call it deliberately (e.g. a
    "detailed forecast" command), not as the default fast path.
    """
    pred_df = forecast_result["pred_df"]
    all_runs = forecast_result.get("all_runs") or [pred_df]
    low_df = forecast_result.get("low_df")
    high_df = forecast_result.get("high_df")
    mean_df = forecast_result.get("mean_df")
    n_runs = forecast_result.get("n_runs", len(all_runs))
    context_start = forecast_result.get("context_start")
    forecast_start = forecast_result.get("forecast_start", hist_df["timestamps"].iloc[-1])

    display_hist = hist_df.tail(display_days)

    plt.figure(figsize=(15, 7.5))

    plt.plot(display_hist["timestamps"], display_hist["close"],
              color="#4c78a8", linewidth=2.2, label="Historical Close (Full Data)")

    for i, run in enumerate(all_runs):
        plt.plot(run["timestamps"], run["close"], color="#f5a623", alpha=0.4, linewidth=1.3,
                  label="Forecast Paths" if i == 0 else None)

    if mean_df is not None:
        plt.plot(mean_df["timestamps"], mean_df["close"], color="#a91e1e",
                  linewidth=3.0, label="Mean Forecast")
    elif len(all_runs) == 1:
        plt.plot(pred_df["timestamps"], pred_df["close"], color="#a91e1e",
                  linewidth=3.0, label="Forecast")

    if low_df is not None and high_df is not None:
        plt.fill_between(pred_df["timestamps"], low_df["close"], high_df["close"],
                          color="#f5a623", alpha=0.18, label="10-90th percentile")

    if context_start is not None and context_start >= display_hist["timestamps"].iloc[0]:
        plt.axvline(context_start, color="#2ca02c", linestyle=":", linewidth=2.0, label="Model Context Start")
    plt.axvline(forecast_start, color="gray", linestyle=":", linewidth=2.0, label="Forecast Start")

    plt.title(f"{ticker} Price Forecast (Kronos) -- {n_runs} sampled path{'s' if n_runs != 1 else ''}")
    plt.xlabel("Date")
    plt.ylabel("Price ($)")
    plt.legend(loc="upper left", fontsize=9)
    plt.grid(alpha=0.25)
    plt.xticks(rotation=30)
    plt.tight_layout()

    if save_path is None:
        save_path = os.path.join(CHARTS_DIR, f"{ticker}_detailed_forecast.png")
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
