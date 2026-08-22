"""
Tests for assistant/providers -- the normalize() contract, registry
lookup, and the fallback behavior in get_history_with_fallback(). All
network calls (yfinance, requests) are mocked/faked; nothing here hits a
real API.
"""
import pandas as pd
import pytest

from assistant.providers.base import MarketDataProvider, ProviderDataError, OHLCV_COLUMNS
from assistant import providers


def _raw_df(n=3):
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": [1.0] * n, "high": [2.0] * n, "low": [0.5] * n,
        "close": [1.5] * n, "volume": [100] * n, "amount": [150.0] * n,
        "extra_col_should_be_dropped": [0] * n,
    })


def test_normalize_selects_and_orders_columns():
    out = MarketDataProvider.normalize(_raw_df())
    assert list(out.columns) == OHLCV_COLUMNS


def test_normalize_sorts_by_timestamp():
    df = _raw_df(3)
    shuffled = df.iloc[[2, 0, 1]].reset_index(drop=True)
    out = MarketDataProvider.normalize(shuffled)
    assert list(out["timestamps"]) == sorted(df["timestamps"])


def test_normalize_drops_duplicate_timestamps():
    df = _raw_df(3)
    dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    out = MarketDataProvider.normalize(dup)
    assert len(out) == 3


def test_normalize_raises_on_missing_columns():
    df = _raw_df().drop(columns=["volume"])
    with pytest.raises(ProviderDataError):
        MarketDataProvider.normalize(df)


class _FakeProvider(MarketDataProvider):
    """A minimal in-memory provider for registry/fallback tests."""
    def __init__(self, name, should_fail=False):
        self.name = name
        self.should_fail = should_fail
        self.calls = []

    def get_history(self, symbol, lookback_days, interval="1d"):
        self.calls.append((symbol, lookback_days, interval))
        if self.should_fail:
            raise ProviderDataError(f"{self.name} has no data for {symbol}")
        return self.normalize(_raw_df())

    def validate_symbol(self, symbol):
        return not self.should_fail


def test_get_provider_unknown_name_raises():
    with pytest.raises(ValueError):
        providers.get_provider("not_a_real_provider")


def test_fallback_used_when_primary_fails(monkeypatch):
    primary = _FakeProvider("primary", should_fail=True)
    fallback = _FakeProvider("fallback", should_fail=False)
    monkeypatch.setattr(providers, "_REGISTRY", {"primary": lambda: primary, "fallback": lambda: fallback})
    monkeypatch.setattr(providers, "_instances", {})
    monkeypatch.setattr(providers, "MARKET_DATA_PROVIDER", "primary")
    monkeypatch.setattr(providers, "MARKET_DATA_FALLBACK_PROVIDER", "fallback")

    df, used = providers.get_history_with_fallback("AAPL", 30)
    assert used == "fallback"
    assert len(fallback.calls) == 1


def test_no_fallback_configured_raises_primary_error(monkeypatch):
    primary = _FakeProvider("primary", should_fail=True)
    monkeypatch.setattr(providers, "_REGISTRY", {"primary": lambda: primary})
    monkeypatch.setattr(providers, "_instances", {})
    monkeypatch.setattr(providers, "MARKET_DATA_PROVIDER", "primary")
    monkeypatch.setattr(providers, "MARKET_DATA_FALLBACK_PROVIDER", "")

    with pytest.raises(ProviderDataError):
        providers.get_history_with_fallback("AAPL", 30)


def test_both_providers_failing_raises_combined_error(monkeypatch):
    primary = _FakeProvider("primary", should_fail=True)
    fallback = _FakeProvider("fallback", should_fail=True)
    monkeypatch.setattr(providers, "_REGISTRY", {"primary": lambda: primary, "fallback": lambda: fallback})
    monkeypatch.setattr(providers, "_instances", {})
    monkeypatch.setattr(providers, "MARKET_DATA_PROVIDER", "primary")
    monkeypatch.setattr(providers, "MARKET_DATA_FALLBACK_PROVIDER", "fallback")

    with pytest.raises(ProviderDataError) as exc_info:
        providers.get_history_with_fallback("AAPL", 30)
    assert "primary" in str(exc_info.value) and "fallback" in str(exc_info.value)


def test_primary_success_does_not_touch_fallback(monkeypatch):
    primary = _FakeProvider("primary", should_fail=False)
    fallback = _FakeProvider("fallback", should_fail=False)
    monkeypatch.setattr(providers, "_REGISTRY", {"primary": lambda: primary, "fallback": lambda: fallback})
    monkeypatch.setattr(providers, "_instances", {})
    monkeypatch.setattr(providers, "MARKET_DATA_PROVIDER", "primary")
    monkeypatch.setattr(providers, "MARKET_DATA_FALLBACK_PROVIDER", "fallback")

    df, used = providers.get_history_with_fallback("AAPL", 30)
    assert used == "primary"
    assert fallback.calls == []
