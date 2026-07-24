"""
Turns raw numbers into a human-readable explanation (item #4: Explainable
Forecasts). This is rule-based (no LLM required), so it always works
offline/without an API key. If assistant.config.ANTHROPIC_API_KEY is set,
assistant.core_assistant can optionally ask an LLM to smooth the wording,
but the reasoning/content itself always comes from these grounded facts.

Supports two registers via `beginner=True/False`: the default is a
compact, jargon-normal style for people already comfortable with technical
analysis; beginner mode spells out what each indicator means in plain
language, at the cost of being more verbose.
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


def build_explanation(ticker, ind_df, forecast_result, news_summary=None,
                       beginner=False, earnings_warning=None):
    """
    ind_df: output of assistant.indicators.compute_indicators on the
            historical data (NOT the forecast).
    forecast_result: output of assistant.forecaster.run_forecast
    news_summary: aggregate dict from assistant.news.get_news (optional)
    beginner: if True, indicator lines spell out what the reading means
              instead of assuming the reader already knows.
    earnings_warning: a datetime.date if an earnings report falls within
              the forecast window (from assistant.fundamentals.earnings_within_horizon),
              or None. When set, a caution sentence is appended.
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
        direction = "upside" if stats["sma_20"] > stats["sma_50"] else "downside"
        if beginner:
            lines.append(
                f"The average price over the last 20 days ({stats['sma_20']:.2f}) is "
                f"{'above' if direction == 'upside' else 'below'} the 50-day average "
                f"({stats['sma_50']:.2f}). When the shorter average is above the longer "
                f"one, it usually means the stock has been gaining momentum recently; "
                f"below usually means it's been losing steam."
            )
        else:
            lines.append(
                f"The 20-day average ({stats['sma_20']:.2f}) is "
                f"{'above' if direction == 'upside' else 'below'} the 50-day "
                f"average ({stats['sma_50']:.2f}), consistent with near-term momentum "
                f"tilted to the {direction}."
            )

    # RSI
    if stats["rsi_14"] is not None:
        rsi = stats["rsi_14"]
        if beginner:
            explainer = ("RSI (Relative Strength Index) measures how fast and how much a "
                         "price has moved recently, on a 0-100 scale.")
            if rsi >= 70:
                lines.append(f"{explainer} It's currently {rsi:.1f} -- above 70 is considered "
                              f"'overbought', meaning the stock has risen quickly and a pause "
                              f"or pullback wouldn't be unusual.")
            elif rsi <= 30:
                lines.append(f"{explainer} It's currently {rsi:.1f} -- below 30 is considered "
                              f"'oversold', meaning the stock has fallen quickly and a bounce "
                              f"wouldn't be unusual.")
            else:
                lines.append(f"{explainer} It's currently {rsi:.1f}, a neutral reading (30-70 "
                              f"is normal) -- no extreme pressure either way right now.")
        else:
            if rsi >= 70:
                lines.append(f"RSI is {rsi:.1f}, in overbought territory -- a pullback risk exists.")
            elif rsi <= 30:
                lines.append(f"RSI is {rsi:.1f}, in oversold territory -- a bounce is plausible.")
            else:
                lines.append(f"RSI is {rsi:.1f}, a neutral reading with no extreme pressure either way.")

    # MACD
    if stats["macd_hist"] is not None and stats["macd_hist_prev"] is not None:
        macd_prefix = ("MACD compares two moving averages to gauge momentum; its histogram "
                        "shows whether that momentum is strengthening or fading. ") if beginner else ""
        if stats["macd_hist"] > 0 and stats["macd_hist"] > stats["macd_hist_prev"]:
            lines.append(f"{macd_prefix}MACD histogram is positive and rising, indicating strengthening bullish momentum.")
        elif stats["macd_hist"] < 0 and stats["macd_hist"] < stats["macd_hist_prev"]:
            lines.append(f"{macd_prefix}MACD histogram is negative and falling, indicating strengthening bearish momentum.")
        else:
            lines.append(f"{macd_prefix}MACD momentum is mixed / losing steam in its current direction.")

    # Volatility / ATR
    if stats["atr_14"] is not None:
        atr_pct = stats["atr_14"] / last_close * 100
        level = "high" if atr_pct > 4 else "moderate" if atr_pct > 2 else "low"
        if beginner:
            lines.append(f"Average True Range (a measure of how much the price typically swings "
                          f"day to day) is {stats['atr_14']:.2f}, about {atr_pct:.1f}% of the price -- "
                          f"a {level} volatility reading, meaning day-to-day moves have been "
                          f"{'large' if level == 'high' else 'moderate' if level == 'moderate' else 'fairly small'}.")
        else:
            lines.append(f"Average True Range is {stats['atr_14']:.2f} ({atr_pct:.1f}% of price), "
                          f"a {level} volatility reading.")

    # Volume
    if stats["volume_sma_20"]:
        vol_ratio = stats["volume"] / stats["volume_sma_20"]
        if vol_ratio > 1.3:
            lines.append("Trading volume is well above its 20-day average, suggesting elevated interest/conviction.")
        elif vol_ratio < 0.7:
            lines.append("Trading volume is below its 20-day average, suggesting lighter conviction right now.")

    # Support/resistance
    if beginner:
        lines.append(f"Recent support (a price level buyers have stepped in before) sits near "
                      f"{sr['support']:.2f}; resistance (a level sellers have shown up before) is "
                      f"near {sr['resistance']:.2f}.")
    else:
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

    # Earnings caution
    if earnings_warning is not None:
        lines.append(
            f"Heads up: {ticker} has an earnings report expected around {earnings_warning} -- "
            f"that falls within this forecast window, and earnings reports often cause bigger, "
            f"harder-to-predict price moves than the model accounts for."
        )

    return {
        "text": " ".join(lines),
        "pct_change": pct_change,
        "trend": trend,
        "stats": stats,
        "support_resistance": sr,
    }


def build_risk_note(ind_df, news_summary=None, beginner=False):
    """Short, focused answer for follow-up questions like 'what risks should I watch?'"""
    stats = summarize_latest(ind_df)
    risks = []
    if stats["rsi_14"] is not None and stats["rsi_14"] >= 70:
        if beginner:
            risks.append("RSI shows 'overbought' conditions (it's risen quickly) -- short-term pullback risk.")
        else:
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
