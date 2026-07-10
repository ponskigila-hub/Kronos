"""
Turns raw numbers into a human-readable explanation (item #4: Explainable
Forecasts). This is rule-based (no LLM required), so it always works
offline/without an API key. If assistant.config.ANTHROPIC_API_KEY is set,
assistant.core_assistant can optionally ask an LLM to smooth the wording,
but the reasoning/content itself always comes from these grounded facts.
"""
from .indicators import summarize_latest, support_resistance


def _trend_label(pct_change):
    if pct_change > 5:
        return "a strong upward"
    if pct_change > 1:
        return "a modest upward"
    if pct_change < -5:
        return "a strong downward"
    if pct_change < -1:
        return "a modest downward"
    return "a roughly flat"


def build_explanation(ticker, ind_df, forecast_result, news_summary=None):
    """
    ind_df: output of assistant.indicators.compute_indicators on the
            historical data (NOT the forecast).
    forecast_result: output of assistant.forecaster.run_forecast
    news_summary: aggregate dict from assistant.news.get_news (optional)
    """
    stats = summarize_latest(ind_df)
    sr = support_resistance(ind_df)
    pred_df = forecast_result["pred_df"]

    last_close = stats["close"]
    forecast_close = float(pred_df["close"].iloc[-1])
    pct_change = round((forecast_close - last_close) / last_close * 100, 2)
    trend = _trend_label(pct_change)

    lines = []
    lines.append(
        f"Kronos projects {ticker} moving from {last_close:.2f} to "
        f"{forecast_close:.2f} over the next {len(pred_df)} trading days "
        f"({pct_change:+.2f}%) -- {trend} trend."
    )

    # Moving averages / momentum
    if stats["sma_20"] and stats["sma_50"]:
        if stats["sma_20"] > stats["sma_50"]:
            lines.append(
                f"The 20-day average ({stats['sma_20']:.2f}) is above the 50-day "
                f"average ({stats['sma_50']:.2f}), consistent with near-term momentum "
                f"tilted to the upside."
            )
        else:
            lines.append(
                f"The 20-day average ({stats['sma_20']:.2f}) is below the 50-day "
                f"average ({stats['sma_50']:.2f}), consistent with near-term momentum "
                f"tilted to the downside."
            )

    # RSI
    if stats["rsi_14"] is not None:
        rsi = stats["rsi_14"]
        if rsi >= 70:
            lines.append(f"RSI is {rsi:.1f}, in overbought territory -- a pullback risk exists.")
        elif rsi <= 30:
            lines.append(f"RSI is {rsi:.1f}, in oversold territory -- a bounce is plausible.")
        else:
            lines.append(f"RSI is {rsi:.1f}, a neutral reading with no extreme pressure either way.")

    # MACD
    if stats["macd_hist"] is not None and stats["macd_hist_prev"] is not None:
        if stats["macd_hist"] > 0 and stats["macd_hist"] > stats["macd_hist_prev"]:
            lines.append("MACD histogram is positive and rising, indicating strengthening bullish momentum.")
        elif stats["macd_hist"] < 0 and stats["macd_hist"] < stats["macd_hist_prev"]:
            lines.append("MACD histogram is negative and falling, indicating strengthening bearish momentum.")
        else:
            lines.append("MACD momentum is mixed / losing steam in its current direction.")

    # Volatility / ATR
    if stats["atr_14"] is not None:
        atr_pct = stats["atr_14"] / last_close * 100
        lines.append(f"Average True Range is {stats['atr_14']:.2f} ({atr_pct:.1f}% of price), "
                      f"a {'high' if atr_pct > 4 else 'moderate' if atr_pct > 2 else 'low'} volatility reading.")

    # Volume
    if stats["volume_sma_20"]:
        vol_ratio = stats["volume"] / stats["volume_sma_20"]
        if vol_ratio > 1.3:
            lines.append("Trading volume is well above its 20-day average, suggesting elevated interest/conviction.")
        elif vol_ratio < 0.7:
            lines.append("Trading volume is below its 20-day average, suggesting lighter conviction right now.")

    # Support/resistance
    lines.append(f"Recent support sits near {sr['support']:.2f} and resistance near {sr['resistance']:.2f}.")

    # Confidence band
    if forecast_result.get("low_df") is not None:
        low_end = float(forecast_result["low_df"]["close"].iloc[-1])
        high_end = float(forecast_result["high_df"]["close"].iloc[-1])
        lines.append(f"Across {forecast_result['n_runs']} independent sampling runs, the forecast "
                      f"range at the horizon is roughly {low_end:.2f} to {high_end:.2f}.")

    # News
    if news_summary and news_summary.get("label") != "no data":
        lines.append(
            f"Recent news sentiment is {news_summary['label']} "
            f"({news_summary['positive']} positive / {news_summary['negative']} negative / "
            f"{news_summary['neutral']} neutral headlines)."
        )

    return {
        "text": " ".join(lines),
        "pct_change": pct_change,
        "trend": trend,
        "stats": stats,
        "support_resistance": sr,
    }


def build_risk_note(ind_df, news_summary=None):
    """Short, focused answer for follow-up questions like 'what risks should I watch?'"""
    stats = summarize_latest(ind_df)
    risks = []
    if stats["rsi_14"] is not None and stats["rsi_14"] >= 70:
        risks.append("RSI shows overbought conditions -- short-term pullback risk.")
    if stats["rsi_14"] is not None and stats["rsi_14"] <= 30:
        risks.append("RSI shows oversold conditions -- can stay oversold longer than expected.")
    if stats["atr_14"] is not None and stats["close"]:
        atr_pct = stats["atr_14"] / stats["close"] * 100
        if atr_pct > 4:
            risks.append(f"Volatility is elevated (ATR {atr_pct:.1f}% of price) -- expect larger swings.")
    if news_summary and news_summary.get("label") == "mostly negative":
        risks.append("Recent news skews negative, which can pressure sentiment-driven moves.")
    if not risks:
        risks.append("No major red flags in the current indicator set -- main risk is general market volatility.")
    return risks
