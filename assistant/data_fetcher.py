"""
Replaces the old "download a CSV by hand" step (yahoopredict.py did this
once, for AAPL only, with no validation). This module is the default data
pipeline: given a ticker, it validates, downloads (via a swappable
MarketDataProvider -- see assistant/providers/), and caches history into
the exact schema Kronos expects.

fetch_history / fetch_multi / TickerNotFoundError keep the exact same
signatures and behavior they had before the provider abstraction existed
-- every caller in this project (core_assistant, forecaster docstring,
portfolio_analysis, screener, webapp) uses only these three names, so
none of them needed to change.
"""
import time

from .ticker_utils import validate_ticker
from .config import DEFAULT_LOOKBACK_DAYS
from .providers import get_history_with_fallback, ProviderDataError

KRONOS_COLUMNS = ["open", "high", "low", "close", "volume", "amount"]

# Short-lived cache for fetch_history(). A single chat turn on a ticker
# routinely triggers several handlers in a row that each want the same
# history (forecast -> "why is it moving" -> "what risks" -> "backtest"),
# and re-fetching identical daily OHLCV every time was pure wasted
# latency. 3 minutes is long enough to cover a back-and-forth about one
# ticker but short enough that intraday price moves during market hours
# still show up on the next fresh ask. This cache lives here (not inside
# each provider) because it's provider-agnostic: the normalized output is
# identical regardless of which provider produced it.
_HISTORY_CACHE_TTL = 180
_history_cache = {}  # (symbol, lookback_days, interval) -> (fetched_at, df)


class TickerNotFoundError(Exception):
    pass


def fetch_history(ticker, lookback_days=None, interval="1d"):
    """
    Fetch and clean historical OHLCV data for a single ticker via the
    configured MarketDataProvider, returning a DataFrame in Kronos's
    expected format:
        columns: open, high, low, close, volume, amount
        plus a 'timestamps' column (datetime64)

    Raises TickerNotFoundError if the symbol doesn't exist / no provider
    (including the fallback, if configured) has data for it.
    """
    is_valid, symbol = validate_ticker(ticker)
    if not is_valid:
        raise TickerNotFoundError(
            f"'{ticker}' does not look like a valid ticker on Yahoo Finance."
        )

    lookback_days = lookback_days or DEFAULT_LOOKBACK_DAYS
    cache_key = (symbol, lookback_days, interval)
    cached = _history_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < _HISTORY_CACHE_TTL:
        return cached[1].copy()

    try:
        df, provider_used = get_history_with_fallback(symbol, lookback_days, interval)
    except ProviderDataError as e:
        raise TickerNotFoundError(str(e))

    result = df  # already normalized (timestamps, open, high, low, close, volume, amount)
    _history_cache[cache_key] = (time.time(), result)
    return result.copy()


def fetch_multi(tickers, lookback_days=None, interval="1d"):
    """Fetch several tickers at once. Returns {ticker: df_or_None}, plus a
    list of tickers that failed to resolve."""
    results = {}
    failures = []
    for t in tickers:
        try:
            results[t] = fetch_history(t, lookback_days=lookback_days, interval=interval)
        except TickerNotFoundError:
            failures.append(t)
    return results, failures

