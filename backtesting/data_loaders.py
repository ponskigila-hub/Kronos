"""
Interchangeable data loaders (requirement #12). All loaders implement the
same interface: `.load(symbol, start=None, end=None) -> DataFrame` with
columns `[timestamps, open, high, low, close, volume, amount]`, matching
what assistant.data_fetcher already produces -- so the rest of the
backtesting framework doesn't care which source the data came from.

Fully implemented (no paid account needed):
  - YahooFinanceLoader (reuses assistant.data_fetcher)
  - CSVLoader

Stubbed with clear extension points (need a paid API key / SDK / broker
connection, which we can't provision here -- fill in `_fetch_raw` and the
rest of the framework works unchanged):
  - PolygonLoader
  - AlphaVantageLoader
  - BinanceLoader
  - InteractiveBrokersLoader
"""
import pandas as pd

from assistant.data_fetcher import fetch_history, KRONOS_COLUMNS


class DataLoader:
    """Base interface every loader implements."""

    def load(self, symbol, start=None, end=None, lookback_days=None):
        raise NotImplementedError


class YahooFinanceLoader(DataLoader):
    def load(self, symbol, start=None, end=None, lookback_days=1500):
        df = fetch_history(symbol, lookback_days=lookback_days)
        if start is not None:
            df = df[df["timestamps"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["timestamps"] <= pd.Timestamp(end)]
        return df.reset_index(drop=True)


class CSVLoader(DataLoader):
    """
    Expects a CSV with at least timestamps/date + OHLCV columns. Column
    names are auto-detected case-insensitively; adjust `column_map` if your
    file uses different names.
    """

    def __init__(self, column_map=None):
        self.column_map = column_map or {
            "date": "timestamps", "datetime": "timestamps",
            "open": "open", "high": "high", "low": "low", "close": "close",
            "volume": "volume", "amount": "amount",
        }

    def load(self, symbol, start=None, end=None, lookback_days=None):
        # `symbol` is treated as a file path for the CSV loader.
        df = pd.read_csv(symbol)
        df.columns = [c.strip().lower() for c in df.columns]
        df = df.rename(columns={k: v for k, v in self.column_map.items() if k in df.columns})
        df["timestamps"] = pd.to_datetime(df["timestamps"])
        if "amount" not in df.columns:
            df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
        df = df.sort_values("timestamps").reset_index(drop=True)
        if start is not None:
            df = df[df["timestamps"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["timestamps"] <= pd.Timestamp(end)]
        if lookback_days:
            df = df.tail(lookback_days)
        return df[["timestamps"] + KRONOS_COLUMNS].reset_index(drop=True)


class PolygonLoader(DataLoader):
    """Extension point -- requires a Polygon.io API key and the `polygon-api-client`
    package. Implement `_fetch_raw` and this loader plugs into the rest of the
    framework unchanged."""

    def __init__(self, api_key):
        self.api_key = api_key

    def load(self, symbol, start=None, end=None, lookback_days=None):
        raise NotImplementedError(
            "PolygonLoader is a stub -- implement _fetch_raw() using the "
            "polygon-api-client SDK and your POLYGON_API_KEY, then reshape "
            "the result to [timestamps, open, high, low, close, volume, amount]."
        )


class AlphaVantageLoader(DataLoader):
    """Extension point -- requires ALPHAVANTAGE_API_KEY (already read into
    assistant.config.ALPHAVANTAGE_API_KEY). Alpha Vantage's free tier is
    rate-limited (5 calls/min), which matters a lot for walk-forward
    backtesting since it re-fetches per window -- prefer YahooFinanceLoader
    and fetch once, then slice, unless you specifically need AV's data."""

    def __init__(self, api_key):
        self.api_key = api_key

    def load(self, symbol, start=None, end=None, lookback_days=None):
        raise NotImplementedError(
            "AlphaVantageLoader is a stub -- implement using the "
            "TIME_SERIES_DAILY endpoint and your ALPHAVANTAGE_API_KEY."
        )


class BinanceLoader(DataLoader):
    """Extension point for crypto data via Binance's public klines endpoint
    (no API key needed for historical OHLCV, but rate-limited)."""

    def load(self, symbol, start=None, end=None, lookback_days=None):
        raise NotImplementedError(
            "BinanceLoader is a stub -- implement using Binance's "
            "/api/v3/klines endpoint (requests library) and reshape to "
            "[timestamps, open, high, low, close, volume, amount]. Note "
            "assistant.data_fetcher already covers crypto via Yahoo Finance "
            "tickers like 'BTC-USD', which may be simpler for most uses."
        )


class InteractiveBrokersLoader(DataLoader):
    """Extension point -- requires `ib_insync` (or the official `ibapi`) and
    a running TWS/IB Gateway connection, which can't be provisioned in this
    environment. Left as a stub."""

    def load(self, symbol, start=None, end=None, lookback_days=None):
        raise NotImplementedError(
            "InteractiveBrokersLoader is a stub -- requires a live TWS/IB "
            "Gateway connection via ib_insync. Implement _fetch_raw() there."
        )


LOADERS = {
    "yahoo": YahooFinanceLoader,
    "csv": CSVLoader,
    "polygon": PolygonLoader,
    "alphavantage": AlphaVantageLoader,
    "binance": BinanceLoader,
    "ibkr": InteractiveBrokersLoader,
}


def get_loader(name, **kwargs):
    if name not in LOADERS:
        raise ValueError(f"Unknown data source '{name}'. Options: {list(LOADERS)}")
    return LOADERS[name](**kwargs)
