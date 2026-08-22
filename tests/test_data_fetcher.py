"""
Confirms assistant.data_fetcher.fetch_history's external contract
(signature, TickerNotFoundError, caching) is unchanged after being
refactored to delegate through assistant.providers, using a fully faked
provider layer so no real network call happens.
"""
import time

import pandas as pd
import pytest

from assistant import data_fetcher
from assistant.providers.base import ProviderDataError


def _fake_df(n=5):
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
        "close": [100.5] * n, "volume": [1000] * n, "amount": [100500.0] * n,
    })


@pytest.fixture(autouse=True)
def clean_state():
    data_fetcher._history_cache.clear()
    yield
    data_fetcher._history_cache.clear()


def test_fetch_history_raises_ticker_not_found_on_provider_error(monkeypatch):
    monkeypatch.setattr(data_fetcher, "validate_ticker", lambda t: (True, t.upper()))

    def fail(*a, **kw):
        raise ProviderDataError("no data anywhere")
    monkeypatch.setattr(data_fetcher, "get_history_with_fallback", fail)

    with pytest.raises(data_fetcher.TickerNotFoundError):
        data_fetcher.fetch_history("BADTICKER")


def test_fetch_history_raises_ticker_not_found_on_invalid_symbol(monkeypatch):
    monkeypatch.setattr(data_fetcher, "validate_ticker", lambda t: (False, t.upper()))
    with pytest.raises(data_fetcher.TickerNotFoundError):
        data_fetcher.fetch_history("NOTASYMBOL")


def test_fetch_history_returns_provider_dataframe(monkeypatch):
    monkeypatch.setattr(data_fetcher, "validate_ticker", lambda t: (True, "AAPL"))
    monkeypatch.setattr(
        data_fetcher, "get_history_with_fallback",
        lambda symbol, lookback_days, interval="1d": (_fake_df(), "yfinance"),
    )
    df = data_fetcher.fetch_history("aapl", lookback_days=5)
    assert list(df.columns) == ["timestamps", "open", "high", "low", "close", "volume", "amount"]
    assert len(df) == 5


def test_fetch_history_uses_cache_on_second_call(monkeypatch):
    monkeypatch.setattr(data_fetcher, "validate_ticker", lambda t: (True, "AAPL"))
    calls = []

    def fake_get(symbol, lookback_days, interval="1d"):
        calls.append(1)
        return _fake_df(), "yfinance"

    monkeypatch.setattr(data_fetcher, "get_history_with_fallback", fake_get)
    data_fetcher.fetch_history("AAPL", lookback_days=5)
    data_fetcher.fetch_history("AAPL", lookback_days=5)
    assert len(calls) == 1  # second call served from cache, no provider hit


def test_fetch_history_cache_expires(monkeypatch):
    monkeypatch.setattr(data_fetcher, "validate_ticker", lambda t: (True, "AAPL"))
    monkeypatch.setattr(data_fetcher, "_HISTORY_CACHE_TTL", 0)
    calls = []

    def fake_get(symbol, lookback_days, interval="1d"):
        calls.append(1)
        return _fake_df(), "yfinance"

    monkeypatch.setattr(data_fetcher, "get_history_with_fallback", fake_get)
    data_fetcher.fetch_history("AAPL", lookback_days=5)
    time.sleep(0.01)
    data_fetcher.fetch_history("AAPL", lookback_days=5)
    assert len(calls) == 2  # TTL of 0 means the second call must refetch


def test_fetch_multi_reports_failures(monkeypatch):
    monkeypatch.setattr(data_fetcher, "validate_ticker",
                         lambda t: (t != "BAD", t.upper()))

    def fake_get(symbol, lookback_days, interval="1d"):
        return _fake_df(), "yfinance"
    monkeypatch.setattr(data_fetcher, "get_history_with_fallback", fake_get)

    results, failures = data_fetcher.fetch_multi(["AAPL", "BAD", "MSFT"])
    assert set(results.keys()) == {"AAPL", "MSFT"}
    assert failures == ["BAD"]
