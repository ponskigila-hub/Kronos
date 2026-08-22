"""
The provider-agnostic contract for market data.

Every concrete provider (YFinanceProvider, TwelveDataProvider, ...) must
normalize whatever schema its upstream API returns into this exact shape,
so that everything downstream of it -- Kronos, indicators, charts,
backtesting -- never knows or cares where the bytes came from:

    columns: timestamps, open, high, low, close, volume, amount
    (amount = volume * average price for the bar, since Kronos was trained
     on that as a feature; it's rarely provided directly by any API)

This module intentionally defines only what the rest of the project
actually uses today (get_history, validate_symbol) plus get_quote, which
nothing currently calls but is small, obviously useful for a future
"current price without a full history pull" need, and costs nothing to
standardize now while the interface is already being designed. It does
NOT define get_news or get_fundamentals -- assistant/news.py and
assistant/fundamentals.py already implement their own multi-source
waterfalls (yfinance -> Finnhub -> NewsAPI for news; yfinance for
fundamentals) independently of OHLCV sourcing, and folding them into this
interface wouldn't simplify anything today. See PROVIDERS.md for the
full rationale and the provider comparison table.
"""
from abc import ABC, abstractmethod

import pandas as pd

OHLCV_COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]


class ProviderDataError(Exception):
    """Raised when a provider can't produce data for a symbol -- covers
    both 'symbol doesn't exist' and 'API/network failure', since callers
    (data_fetcher.fetch_history) currently treat both the same way: try
    a fallback provider if one is configured, otherwise surface as
    TickerNotFoundError."""
    pass


class MarketDataProvider(ABC):
    #: Short machine-readable name, used in the MARKET_DATA_PROVIDER /
    #: MARKET_DATA_FALLBACK_PROVIDER env vars and in log messages.
    name = "base"

    @abstractmethod
    def get_history(self, symbol: str, lookback_days: int, interval: str = "1d") -> pd.DataFrame:
        """
        Return a DataFrame with exactly OHLCV_COLUMNS, sorted ascending by
        timestamp, containing at most `lookback_days` most-recent rows.
        Must raise ProviderDataError (not return an empty/partial frame)
        if the symbol is invalid or no data is available, so callers can
        distinguish "legitimately nothing to show" from "this provider
        doesn't have it, try the fallback."
        """
        raise NotImplementedError

    @abstractmethod
    def validate_symbol(self, symbol: str) -> bool:
        """Cheap existence check, used by ticker resolution in chat/NLP."""
        raise NotImplementedError

    def get_quote(self, symbol: str) -> dict:
        """
        Optional: {"price": float, "currency": str, "as_of": str}.
        Not required by any current caller -- providers that don't
        implement it can leave this raising NotImplementedError; callers
        that want it should catch that and fall back to the last close
        from get_history() instead of assuming every provider has it.
        """
        raise NotImplementedError

    @staticmethod
    def normalize(df: pd.DataFrame) -> pd.DataFrame:
        """Shared final-shape guard every provider should run its raw,
        renamed DataFrame through before returning -- catches column-order
        drift and enforces sorted/deduplicated timestamps in one place."""
        missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
        if missing:
            raise ProviderDataError(f"Provider output missing columns: {missing}")
        df = df[OHLCV_COLUMNS].copy()
        df["timestamps"] = pd.to_datetime(df["timestamps"])
        df = df.drop_duplicates(subset=["timestamps"]).sort_values("timestamps")
        return df.reset_index(drop=True)
