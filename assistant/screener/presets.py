"""
Named screening strategies (project brief #16). Each preset is just:
  - a set of hard filters (tickers failing these are excluded outright,
    not merely scored lower) expressed as (metric_path, operator, value)
    triples -- the same shape screener/filters.py evaluates for a fully
    custom screen, so a preset is really just a pre-built custom filter
  - optional weight overrides, applied over scoring.DEFAULT_WEIGHTS

Filters reference metric dict keys from screener/metrics.py directly
(e.g. "momentum_rsi14", "trend_price_vs_sma200"), so adding a new preset
never requires touching metrics.py or the filter engine.
"""
from . import filters as filters_mod

PRESETS = {
    "momentum": {
        "label": "Momentum",
        "description": "Strong recent performance, positive momentum, healthy volume, bullish trend.",
        "filters": [
            ("trend_return_3m", ">", 0.05),
            ("momentum_rsi14", ">", 50),
            ("momentum_rsi14", "<", 80),
            ("rs_blend", ">", 0),
            ("liquidity_relative_volume", ">", 0.8),
        ],
        "weights": {"trend": 0.25, "momentum": 0.30, "relative_strength": 0.20,
                    "volatility": 0.05, "liquidity": 0.10, "risk": 0.05, "kronos": 0.05},
    },
    "breakout": {
        "label": "Breakout",
        "description": "Near 52-week highs, rising volume, strong trend, volatility contraction before expansion.",
        "filters": [
            ("price_dist_from_52w_high", ">", -0.08),
            ("liquidity_relative_volume", ">", 1.1),
            ("momentum_adx", ">", 18),
            ("momentum_macd_bullish", "==", True),
        ],
        "weights": {"trend": 0.20, "momentum": 0.25, "relative_strength": 0.15,
                    "volatility": 0.20, "liquidity": 0.10, "risk": 0.05, "kronos": 0.05},
    },
    "trend_following": {
        "label": "Trend Following",
        "description": "Price above SMA200, SMA50 above SMA200, positive slope, controlled volatility.",
        "filters": [
            ("trend_price_vs_sma200", ">", 0),
            ("trend_sma50_vs_sma200", ">", 0),
            ("trend_sma50_slope", ">", 0),
        ],
        "weights": {"trend": 0.35, "momentum": 0.15, "relative_strength": 0.15,
                    "volatility": 0.10, "liquidity": 0.10, "risk": 0.15, "kronos": 0.0},
    },
    "pullback": {
        "label": "Pullback",
        "description": "Long-term uptrend with short-term weakness -- RSI recovering, price near moving-average support.",
        "filters": [
            ("trend_price_vs_sma200", ">", 0),
            ("trend_return_1y", ">", 0.05),
            ("momentum_rsi14", "<", 55),
            ("momentum_rsi14", ">", 30),
            ("trend_return_20d", "<", 0.02),
        ],
        "weights": {"trend": 0.25, "momentum": 0.15, "relative_strength": 0.10,
                    "volatility": 0.10, "liquidity": 0.10, "risk": 0.15, "kronos": 0.15},
    },
    "conservative": {
        "label": "Conservative",
        "description": "Strong liquidity, lower volatility, positive trend, low drawdown, strong risk-adjusted returns.",
        "filters": [
            ("trend_price_vs_sma200", ">", 0),
            ("risk_sharpe", ">", 0.3),
            ("risk_max_drawdown_1y", ">", -0.30),
            ("liquidity_avg_dollar_volume_20d", ">", 5_000_000),
        ],
        "weights": {"trend": 0.20, "momentum": 0.10, "relative_strength": 0.10,
                    "volatility": 0.15, "liquidity": 0.15, "risk": 0.30, "kronos": 0.0},
    },
    "kronos_candidates": {
        "label": "Kronos Candidates",
        "description": "Sufficient history, stable price behavior, strong technicals, good liquidity, favorable recent momentum -- pre-filtered for the tickers most worth spending a Kronos forecast on.",
        "filters": [
            ("history_days", ">=", 300),
            ("liquidity_avg_dollar_volume_20d", ">", 3_000_000),
            ("volatility_regime", "!=", "Extreme Volatility"),
            ("trend_regime", "in", ["Strong Uptrend", "Uptrend", "Neutral"]),
        ],
        "weights": {"trend": 0.20, "momentum": 0.20, "relative_strength": 0.15,
                    "volatility": 0.10, "liquidity": 0.15, "risk": 0.10, "kronos": 0.10},
        "force_kronos": True,
    },
    "none": {
        "label": "None (all defaults)",
        "description": "No preset filters -- rank the whole universe with default weights.",
        "filters": [],
        "weights": None,
    },
}


def get(preset_key):
    return PRESETS.get(preset_key, PRESETS["none"])


def apply_preset_filters(metrics, preset_key):
    preset = get(preset_key)
    return filters_mod.evaluate_all(metrics, preset["filters"])


def preset_weights(preset_key):
    preset = get(preset_key)
    return preset.get("weights")
