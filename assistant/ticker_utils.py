"""
Resolves free-form user text ("apple", "AAPL", "bitcoin") into validated
Yahoo Finance ticker symbols.
"""
import re
import yfinance as yf

# A small set of common aliases so users don't have to know exact tickers.
# This is intentionally short -- anything not listed here is simply
# uppercased and validated directly against Yahoo Finance.
COMPANY_ALIASES = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "meta": "META",
    "facebook": "META",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "amd": "AMD",
    "netflix": "NFLX",
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
    "ethereum": "ETH-USD",
    "eth": "ETH-USD",
    "dogecoin": "DOGE-USD",
    "gold": "GC=F",
    "silver": "SI=F",
    "oil": "CL=F",
    "s&p": "^GSPC",
    "s&p500": "^GSPC",
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow": "^DJI",
    "dow jones": "^DJI",
    "ibm": "IBM",
    "intel": "INTC",
}

_TICKER_RE = re.compile(r"^[A-Z0-9\.\-\^=]{1,12}$")

_validation_cache = {}


def resolve_alias(text):
    """Map a free-text company/asset name to a ticker symbol if known."""
    key = text.strip().lower()
    return COMPANY_ALIASES.get(key)


def looks_like_ticker(token):
    """Cheap structural check before we hit the network."""
    return bool(_TICKER_RE.match(token.upper()))


def validate_ticker(symbol, use_cache=True):
    """
    Confirm a ticker actually exists on Yahoo Finance by requesting a small
    slice of recent history. Returns (is_valid, resolved_symbol).
    """
    symbol = symbol.upper().strip()
    if use_cache and symbol in _validation_cache:
        return _validation_cache[symbol], symbol

    is_valid = False
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        is_valid = hist is not None and not hist.empty
    except Exception:
        is_valid = False

    _validation_cache[symbol] = is_valid
    return is_valid, symbol


def extract_tickers(text, max_tickers=5):
    """
    Pull one or more ticker symbols out of a free-text message.

    Strategy:
    1. Try known company-name aliases (multi-word aware).
    2. Fall back to scanning capitalized/alphanumeric tokens that look like
       tickers and validating them against Yahoo Finance.
    """
    found = []
    lowered = text.lower()

    # 1. alias matching (longest alias first so "s&p 500" beats "s&p")
    for alias in sorted(COMPANY_ALIASES, key=len, reverse=True):
        if alias in lowered and COMPANY_ALIASES[alias] not in found:
            found.append(COMPANY_ALIASES[alias])
            lowered = lowered.replace(alias, " ")

    if len(found) >= max_tickers:
        return found[:max_tickers]

    # 2. raw token scan for things like "AAPL", "BTC-USD".
    # \b...\b anchors ensure we only match whole words -- without them a
    # long word like "COMPARE" or "WATCHLIST" gets sliced into bogus
    # fragments ("COMPAR"+"E", "WATCHL"+"IST") that then get validated
    # against Yahoo Finance for nothing.
    tokens = re.findall(r"\b[A-Za-z]{1,6}(?:[\.\-][A-Za-z]{1,4})?\b", text)
    stopwords = {
        "a", "an", "the", "is", "are", "for", "and", "vs", "compare",
        "forecast", "predict", "show", "me", "why", "what", "risks",
        "watch", "history", "stock", "stocks", "price", "next", "days",
        "day", "of", "to", "in", "on", "my", "watchlist", "add", "remove",
        "list", "with", "against", "week", "month", "please", "can", "you",
        "hi", "hello", "hey", "help", "start", "it", "will", "be",
        "this", "that", "expected", "declining", "rising", "falling",
        "should", "would", "could", "about", "over", "at", "by",
        "mode", "simple", "plain", "expert", "beginner", "advanced",
        "target", "rating", "ratings", "cap", "when", "does", "eps",
        "fundamentals", "earnings", "analyst", "correlation", "diversify",
        "ratio", "report", "reports", "use", "switch", "of", "the",
    }
    for tok in tokens:
        if tok.lower() in stopwords:
            continue
        if not looks_like_ticker(tok):
            continue
        candidate = tok.upper()
        if candidate in found:
            continue
        is_valid, resolved = validate_ticker(candidate)
        if is_valid:
            found.append(resolved)
        if len(found) >= max_tickers:
            break

    return found
