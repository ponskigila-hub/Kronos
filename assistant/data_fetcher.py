"""
Replaces the old "download a CSV by hand" step (yahoopredict.py did this
once, for AAPL only, with no validation). This module is the default data
pipeline: given a ticker, it downloads, cleans, and reshapes history into
the exact schema Kronos expects.
"""
import pandas as pd
import yfinance as yf

from .ticker_utils import validate_ticker
from .config import DEFAULT_LOOKBACK_DAYS

KRONOS_COLUMNS = ["open", "high", "low", "close", "volume", "amount"]


class TickerNotFoundError(Exception):
    pass


def fetch_history(ticker, lookback_days=None, interval="1d"):
    """
    Download and clean historical OHLCV data for a single ticker, returning
    a DataFrame in Kronos's expected format:
        columns: open, high, low, close, volume, amount
        plus a 'timestamps' column (datetime64)

    Raises TickerNotFoundError if the symbol doesn't exist / has no data.
    """
    is_valid, symbol = validate_ticker(ticker)
    if not is_valid:
        raise TickerNotFoundError(
            f"'{ticker}' does not look like a valid ticker on Yahoo Finance."
        )

    lookback_days = lookback_days or DEFAULT_LOOKBACK_DAYS
    # Pull extra calendar days to survive weekends/holidays and still end up
    # with `lookback_days` trading rows.
    period_days = int(lookback_days * 1.6) + 10

    df = yf.download(
        symbol,
        period=f"{period_days}d",
        interval=interval,
        auto_adjust=False,
        progress=False,
    )

    if df is None or df.empty:
        raise TickerNotFoundError(f"No historical data returned for '{symbol}'.")

    # yfinance sometimes returns a MultiIndex on columns (esp. for multi-ticker
    # calls, but occasionally on single-ticker calls in newer versions too).
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })

    # Handle missing values instead of silently failing: forward-fill small
    # gaps (e.g. a single missing print), then drop any rows that are still
    # incomplete (e.g. leading NaNs before the asset existed).
    df[["open", "high", "low", "close", "volume"]] = (
        df[["open", "high", "low", "close", "volume"]].ffill()
    )
    df = df.dropna(subset=["open", "high", "low", "close"])

    df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)

    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else "Datetime"
    df = df.rename(columns={date_col: "timestamps"})
    df["timestamps"] = pd.to_datetime(df["timestamps"])

    if len(df) > lookback_days:
        df = df.iloc[-lookback_days:].reset_index(drop=True)

    return df[["timestamps"] + KRONOS_COLUMNS].reset_index(drop=True)


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
