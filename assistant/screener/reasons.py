"""
Turns a ticker's already-computed metrics + category scores into a short
list of plain-language "+ reason" / "- risk" bullets (project brief #26).

Deliberately NOT an LLM call -- every bullet here is generated directly
from a specific calculated metric crossing a specific threshold, so the
explanation is always traceable back to a real number and can never
invent a reason that isn't actually true of the data.
"""


def _pct(x):
    return f"{x * 100:+.1f}%" if x is not None else "n/a"


def build_reasons(metrics, category_scores, kronos_result=None):
    """Returns {"strengths": [str, ...], "risks": [str, ...]}."""
    strengths, risks = [], []
    m = metrics

    # ---- trend
    if m.get("trend_regime") in ("Strong Uptrend", "Uptrend"):
        strengths.append(f"{m['trend_regime']} -- price above both SMA50 and SMA200")
    elif m.get("trend_regime") in ("Downtrend", "Strong Downtrend"):
        risks.append(f"{m['trend_regime']} -- price below key moving averages")

    if (m.get("trend_return_6m") or 0) > 0.15:
        strengths.append(f"Strong 6M momentum ({_pct(m['trend_return_6m'])})")
    elif (m.get("trend_return_6m") or 0) < -0.15:
        risks.append(f"Weak 6M performance ({_pct(m['trend_return_6m'])})")

    # ---- relative strength
    rs_class = m.get("rs_classification")
    if rs_class in ("Strong Outperformance", "Outperformance"):
        strengths.append(f"{rs_class} vs. benchmark ({_pct(m.get('rs_blend'))} blended)")
    elif rs_class in ("Strong Underperformance", "Underperformance"):
        risks.append(f"{rs_class} vs. benchmark ({_pct(m.get('rs_blend'))} blended)")

    # ---- momentum
    rsi = m.get("momentum_rsi14")
    if rsi is not None:
        if rsi > 75:
            risks.append(f"RSI approaching overbought ({rsi:.0f})")
        elif rsi < 30:
            risks.append(f"RSI in oversold territory ({rsi:.0f})")
        elif 50 <= rsi <= 68:
            strengths.append(f"Healthy bullish RSI ({rsi:.0f})")

    if m.get("momentum_macd_bullish") and m.get("momentum_trend") == "accelerating":
        strengths.append("MACD bullish and accelerating")

    # ---- volatility
    vol_regime = m.get("volatility_regime")
    if vol_regime == "Extreme Volatility":
        risks.append("Elevated volatility (top decile of its own recent range)")
    elif vol_regime == "Low Volatility" and m.get("volatility_state") == "contracting":
        strengths.append("Volatility contracting -- often precedes a breakout move")

    # ---- liquidity
    dv = m.get("liquidity_avg_dollar_volume_20d")
    if dv is not None and dv > 20_000_000:
        strengths.append("Deep liquidity (high 20D avg dollar volume)")
    relvol = m.get("liquidity_relative_volume")
    if relvol is not None and relvol > 1.5:
        strengths.append(f"Volume running {relvol:.1f}x its 20D average")

    # ---- price structure
    structure = m.get("price_structure")
    if structure in ("Near Breakout", "At 52-Week High"):
        strengths.append(f"{structure} ({_pct(m.get('price_dist_from_52w_high'))} from 52W high)")
    elif structure == "Deep Drawdown":
        risks.append(f"Deep drawdown from its 52W high ({_pct(m.get('price_dist_from_52w_high'))})")

    # ---- risk
    sharpe = m.get("risk_sharpe")
    if sharpe is not None and sharpe > 1.0:
        strengths.append(f"Strong risk-adjusted return (Sharpe {sharpe:.2f})")
    max_dd = m.get("risk_max_drawdown_1y")
    if max_dd is not None and max_dd < -0.35:
        risks.append(f"Large max drawdown over the last year ({_pct(max_dd)})")

    # ---- kronos
    if kronos_result and kronos_result.get("expected_return") is not None:
        er = kronos_result["expected_return"]
        if er > 0.03:
            strengths.append(f"Positive Kronos forecast ({_pct(er)} expected over the forecast horizon)")
        elif er < -0.03:
            risks.append(f"Negative Kronos forecast ({_pct(er)} expected over the forecast horizon)")

    if not strengths:
        strengths.append("No standout strengths -- an average setup across the board")
    if not risks:
        risks.append("No major red flags in the metrics computed here")

    return {"strengths": strengths, "risks": risks}
