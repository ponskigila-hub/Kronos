"""
Turns the raw metrics from screener/metrics.py into transparent 0-100
category scores plus a single weighted composite -- never a black box:
every category score is exposed alongside the metrics that produced it
(see engine.py / reasons.py), so "why did AAPL rank #1" is always
answerable directly from these numbers.

Categories deliberately mirror screener/metrics.py's groups (trend,
momentum, volatility, liquidity, risk, relative_strength) plus an optional
kronos category -- there's no separate "technical" bucket layered on top,
since trend + momentum + volatility already cover that ground and adding
a fourth would double-count the same handful of correlated price moves
(see the project brief's own warning about this).
"""
import numpy as np

DEFAULT_WEIGHTS = {
    "trend": 0.25,
    "momentum": 0.20,
    "relative_strength": 0.15,
    "volatility": 0.10,
    "liquidity": 0.10,
    "risk": 0.10,
    "kronos": 0.10,
}


def _scale(value, low, high):
    """Linearly map value in [low, high] to [0, 100], clipping outside."""
    if value is None:
        return None
    if high == low:
        return 50.0
    pct = (value - low) / (high - low)
    return float(np.clip(pct * 100, 0, 100))


def _avg(*scores):
    vals = [s for s in scores if s is not None]
    return float(np.mean(vals)) if vals else None


REGIME_SCORE = {
    "Strong Uptrend": 100, "Uptrend": 75, "Neutral": 50,
    "Downtrend": 25, "Strong Downtrend": 0, "Unknown": 50,
}


def score_trend(m):
    numeric = _avg(
        _scale(m.get("trend_price_vs_sma200"), -0.20, 0.20),
        _scale(m.get("trend_price_vs_sma50"), -0.15, 0.15),
        _scale(m.get("trend_sma50_vs_sma200"), -0.10, 0.10),
        _scale(m.get("trend_sma50_slope"), -0.01, 0.01),
        _scale(m.get("trend_return_6m"), -0.30, 0.30),
    )
    regime = REGIME_SCORE.get(m.get("trend_regime"), 50)
    if numeric is None:
        return float(regime)
    return round(0.6 * numeric + 0.4 * regime, 1)


def score_momentum(m):
    rsi = m.get("momentum_rsi14")
    # RSI "sweet spot" is ~50-65 (healthy bullish momentum, not yet
    # overbought) -- score falls off on both sides rather than treating
    # RSI as a raw buy/sell line.
    rsi_score = None
    if rsi is not None:
        rsi_score = float(np.clip(100 - abs(rsi - 58) * 1.8, 0, 100))

    adx = m.get("momentum_adx")
    directional = 1 if m.get("momentum_bullish") else -1
    adx_score = None
    if adx is not None:
        strength = _scale(adx, 10, 40)  # trend strength regardless of direction
        adx_score = float(np.clip(50 + directional * (strength - 50) * 0.9, 0, 100)) if strength is not None else None

    macd_score = 65 if m.get("momentum_macd_bullish") else 35
    if m.get("momentum_trend") == "accelerating":
        macd_score += 10
    elif m.get("momentum_trend") == "decelerating":
        macd_score -= 10
    macd_score = float(np.clip(macd_score, 0, 100))

    roc_score = _scale(m.get("momentum_roc10"), -10, 10)

    return round(_avg(rsi_score, adx_score, macd_score, roc_score) or 50.0, 1)


def score_volatility(m):
    regime = m.get("volatility_regime")
    base = {"Low Volatility": 80, "Normal Volatility": 65, "High Volatility": 35,
            "Extreme Volatility": 15, "Unknown": 50}.get(regime, 50)
    if m.get("volatility_state") == "contracting":
        base += 8  # a coiled spring -- often precedes a breakout move
    return round(float(np.clip(base, 0, 100)), 1)


def score_liquidity(m, min_dollar_volume=1_000_000):
    dv = m.get("liquidity_avg_dollar_volume_20d")
    dv_score = None
    if dv is not None and dv > 0 and min_dollar_volume > 0:
        ratio = dv / min_dollar_volume
        dv_score = _scale(np.log10(max(ratio, 0.01)), 0, 2.5)  # 1x threshold->0, ~316x threshold->100
    relvol = m.get("liquidity_relative_volume")
    relvol_score = _scale(relvol, 0.5, 2.0) if relvol is not None else None
    return round(_avg(dv_score, relvol_score) or 50.0, 1)


def score_risk(m):
    sharpe_score = _scale(m.get("risk_sharpe"), -1, 3)
    sortino_score = _scale(m.get("risk_sortino"), -1, 4)
    dd_score = _scale(m.get("risk_max_drawdown_1y"), -0.5, 0.0)
    return round(_avg(sharpe_score, sortino_score, dd_score) or 50.0, 1)


def score_relative_strength(m):
    return round(_scale(m.get("rs_blend"), -0.20, 0.20) or 50.0, 1)


def score_kronos(kronos_result):
    """kronos_result: {"expected_return": float, ...} or None if the
    Kronos stage wasn't run for this ticker."""
    if not kronos_result or kronos_result.get("expected_return") is None:
        return None
    return round(_scale(kronos_result["expected_return"], -0.10, 0.10), 1)


def compute_category_scores(metrics, min_dollar_volume=1_000_000, kronos_result=None):
    return {
        "trend": score_trend(metrics),
        "momentum": score_momentum(metrics),
        "volatility": score_volatility(metrics),
        "liquidity": score_liquidity(metrics, min_dollar_volume),
        "risk": score_risk(metrics),
        "relative_strength": score_relative_strength(metrics),
        "kronos": score_kronos(kronos_result),
    }


def normalize_weights(weights, exclude=None):
    """Drop `exclude` categories (e.g. 'kronos' when it wasn't run) and
    re-scale the rest to sum to 1.0, preserving their relative ratios."""
    exclude = set(exclude or [])
    active = {k: v for k, v in weights.items() if k not in exclude and v}
    total = sum(active.values())
    if total <= 0:
        n = len(active) or 1
        return {k: 1.0 / n for k in active}
    return {k: v / total for k, v in active.items()}


def composite_score(category_scores, weights=None):
    """Returns (overall_0_100, weights_actually_used)."""
    weights = weights or DEFAULT_WEIGHTS
    missing = [k for k, v in category_scores.items() if v is None]
    used_weights = normalize_weights(weights, exclude=missing)
    overall = sum(category_scores[k] * w for k, w in used_weights.items() if category_scores.get(k) is not None)
    return round(overall, 1), used_weights


def classify_signal(overall_score, risk_score):
    """Non-binary signal per the project brief (#20) -- never a bare
    BUY/SELL. `risk_score` can push an otherwise-strong setup into
    "High Risk" instead of "Strong Candidate"."""
    if risk_score is not None and risk_score < 20 and overall_score >= 60:
        return "High Risk"
    if overall_score >= 80:
        return "Strong Candidate"
    if overall_score >= 65:
        return "Candidate"
    if overall_score >= 45:
        return "Neutral"
    return "Weak Candidate"
