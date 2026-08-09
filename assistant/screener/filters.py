"""
Evaluates (metric, operator, value) filter triples against a metrics dict
from screener/metrics.py. Used both by presets.py (each preset is just a
pre-built list of these) and by the web UI's custom-filter builder --
letting a user compose "RSI < 70 AND Price > SMA200 AND ..." without
writing any Python (project brief #17).

All filters are combined with AND (a ticker must pass every one) -- the
UI is a metric/operator/value row-builder, not a boolean-logic editor, so
there is no OR support in v1. That's the one simplification versus the
original brief's "AND/OR" ask; AND-only already covers the six named
presets and any single-strategy custom screen cleanly.

Percent-style metric values (returns, drawdown, price-vs-SMA, etc.) are
stored as raw fractions in metrics.py (0.05 == 5%) -- the UI is expected
to convert a user-typed "5" (meaning 5%) to 0.05 before it reaches here;
see METRIC_CATALOG's `is_percent` flag for which fields need that.
"""

OPERATORS = {
    ">": lambda a, b: a is not None and a > b,
    ">=": lambda a, b: a is not None and a >= b,
    "<": lambda a, b: a is not None and a < b,
    "<=": lambda a, b: a is not None and a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "in": lambda a, b: a in (b if isinstance(b, (list, tuple, set)) else [b]),
    "not in": lambda a, b: a not in (b if isinstance(b, (list, tuple, set)) else [b]),
}

# Exposed to the web UI's filter-builder dropdown: (key, label, is_percent).
# is_percent fields are entered by the user as e.g. "5" for 5% and divided
# by 100 before evaluation -- see webapp/app.py's screener form parsing.
METRIC_CATALOG = [
    ("price", "Price", False),
    ("trend_price_vs_sma20", "Price vs SMA20", True),
    ("trend_price_vs_sma50", "Price vs SMA50", True),
    ("trend_price_vs_sma200", "Price vs SMA200", True),
    ("trend_sma50_vs_sma200", "SMA50 vs SMA200", True),
    ("trend_return_20d", "20D Return", True),
    ("trend_return_50d", "50D Return", True),
    ("trend_return_3m", "3M Return", True),
    ("trend_return_6m", "6M Return", True),
    ("trend_return_1y", "1Y Return", True),
    ("momentum_rsi14", "RSI (14)", False),
    ("momentum_adx", "ADX", False),
    ("momentum_macd_hist", "MACD Histogram", False),
    ("momentum_roc10", "ROC (10D)", False),
    ("volatility_atr_pct", "ATR %", True),
    ("volatility_hist_20d", "Historical Volatility (20D, ann.)", True),
    ("liquidity_avg_dollar_volume_20d", "Avg Dollar Volume (20D)", False),
    ("liquidity_relative_volume", "Relative Volume", False),
    ("price_dist_from_52w_high", "Distance from 52W High", True),
    ("price_dist_from_52w_low", "Distance from 52W Low", True),
    ("risk_max_drawdown_1y", "Max Drawdown (1Y)", True),
    ("risk_sharpe", "Sharpe Ratio", False),
    ("risk_sortino", "Sortino Ratio", False),
    ("risk_beta", "Beta", False),
    ("rs_blend", "Relative Strength (blended)", True),
]

# Set of metric keys whose values are user-entered as whole percent (e.g.
# "5" meaning 5%) and need /100 before being compared against the raw
# fraction stored in metrics.py. Built from METRIC_CATALOG so it can't
# drift out of sync with the dropdown the UI actually offers.
PERCENT_METRICS = {key for key, _label, is_percent in METRIC_CATALOG if is_percent}


def evaluate_one(metrics, metric_key, operator, value):
    if operator not in OPERATORS:
        raise ValueError(f"Unknown operator '{operator}'.")
    actual = metrics.get(metric_key)
    return OPERATORS[operator](actual, value)


def evaluate_all(metrics, filter_triples):
    """Returns (passed: bool, failed_on: list[str]) -- failed_on names
    which filters knocked the ticker out, for the data-quality summary."""
    failed = []
    for metric_key, operator, value in filter_triples:
        try:
            if not evaluate_one(metrics, metric_key, operator, value):
                failed.append(f"{metric_key} {operator} {value}")
        except Exception:
            failed.append(f"{metric_key} {operator} {value} (unavailable)")
    return (len(failed) == 0), failed
