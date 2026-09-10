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


# ---------------------------------------------------------------------------
# Intraday fetch for the chart popup's "1D"/"1W" ranges (see
# webapp/app.py's api_chart). Deliberately separate from fetch_history()
# rather than bolted onto it: fetch_history's `lookback_days` is a
# *row-count* trim applied after requesting `lookback_days * 1.6 + 10`
# *calendar* days from the provider -- a formula tuned for daily bars,
# where 1 row ~= 1 calendar day. For intraday intervals that ratio is off
# by 10-50x (a single trading day is ~78 five-minute bars), so reusing it
# would either request far more intraday history than Yahoo actually
# serves (5m/15m data is only available for a recent rolling window) or
# silently truncate to the wrong slice. Using yfinance's own documented
# period/interval pairs directly (e.g. period="1d"+interval="5m") avoids
# guessing at that boundary. This only backs the chart popup -- nothing
# else in the app (forecast, backtest, screener) uses intraday data.
_INTRADAY_CACHE_TTL = 60
_intraday_cache = {}  # (symbol, period, interval) -> (fetched_at, df)

_INTRADAY_RANGES = {
    "1D": ("1d", "5m"),
    "1W": ("5d", "15m"),
}


def fetch_intraday(ticker, range_key):
    """
    Chart-popup-only intraday fetch. `range_key` must be one of
    _INTRADAY_RANGES ("1D", "1W"). Returns the same normalized schema as
    fetch_history (timestamps, open, high, low, close, volume, amount).
    Raises TickerNotFoundError on an invalid ticker or no data (e.g. the
    market's been closed long enough that "1D" has nothing recent, or the
    symbol is something like a mutual fund that Yahoo doesn't serve
    intraday bars for at all -- callers should be ready to fall back to
    a daily range in that case).
    """
    import pandas as pd
    import yfinance as yf

    if range_key not in _INTRADAY_RANGES:
        raise ValueError(f"Unsupported intraday range '{range_key}' -- expected one of {list(_INTRADAY_RANGES)}")

    is_valid, symbol = validate_ticker(ticker)
    if not is_valid:
        raise TickerNotFoundError(f"'{ticker}' does not look like a valid ticker on Yahoo Finance.")

    period, interval = _INTRADAY_RANGES[range_key]
    cache_key = (symbol, period, interval)
    cached = _intraday_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < _INTRADAY_CACHE_TTL:
        return cached[1].copy()

    df = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise TickerNotFoundError(
            f"No intraday data available for '{symbol}' -- markets may be closed, "
            f"or this symbol doesn't have intraday bars on Yahoo Finance."
        )

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
    })
    df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].ffill()
    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        raise TickerNotFoundError(f"No usable intraday rows for '{symbol}' after cleaning.")

    df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
    df = df.reset_index()
    date_col = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={date_col: "timestamps"})

    result = df[["timestamps"] + KRONOS_COLUMNS].reset_index(drop=True)
    _intraday_cache[cache_key] = (time.time(), result)
    return result.copy()

