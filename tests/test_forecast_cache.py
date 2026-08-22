"""
Unit tests for assistant/forecast_cache.py -- pure in-memory logic, no
Kronos model or network access required.
"""
import time

import pandas as pd
import pytest

from assistant import forecast_cache


def _sample_df(n=5, seed=0.0):
    return pd.DataFrame({
        "open": [100.0 + i + seed for i in range(n)],
        "high": [101.0 + i + seed for i in range(n)],
        "low": [99.0 + i + seed for i in range(n)],
        "close": [100.5 + i + seed for i in range(n)],
        "volume": [1000 + i for i in range(n)],
        "amount": [100000 + i for i in range(n)],
    })


def _sample_ts(n=5):
    return pd.Series(pd.date_range("2026-01-01", periods=n, freq="B"))


@pytest.fixture(autouse=True)
def clean_cache():
    forecast_cache.clear()
    yield
    forecast_cache.clear()


def test_identical_inputs_produce_identical_key():
    df, ts = _sample_df(), _sample_ts()
    k1 = forecast_cache.make_key(df, ts, 14, 1, 5, 0.7, 0.9, 5, True)
    k2 = forecast_cache.make_key(df.copy(), ts.copy(), 14, 1, 5, 0.7, 0.9, 5, True)
    assert k1 == k2


def test_different_data_produces_different_key():
    ts = _sample_ts()
    k1 = forecast_cache.make_key(_sample_df(seed=0.0), ts, 14, 1, 5, 0.7, 0.9, 5, True)
    k2 = forecast_cache.make_key(_sample_df(seed=1.0), ts, 14, 1, 5, 0.7, 0.9, 5, True)
    assert k1 != k2


def test_different_params_produce_different_key():
    df, ts = _sample_df(), _sample_ts()
    base = forecast_cache.make_key(df, ts, 14, 1, 5, 0.7, 0.9, 5, True)
    diff_pred_len = forecast_cache.make_key(df, ts, 30, 1, 5, 0.7, 0.9, 5, True)
    diff_n_runs = forecast_cache.make_key(df, ts, 14, 3, 5, 0.7, 0.9, 5, True)
    diff_anchor = forecast_cache.make_key(df, ts, 14, 1, 5, 0.7, 0.9, 5, False)
    assert len({base, diff_pred_len, diff_n_runs, diff_anchor}) == 4


def test_get_set_roundtrip():
    key = "abc123"
    assert forecast_cache.get(key) is None
    forecast_cache.set(key, {"pred_df": "fake"})
    assert forecast_cache.get(key) == {"pred_df": "fake"}


def test_hit_and_miss_counters():
    forecast_cache.set("k1", "v1")
    forecast_cache.get("k1")  # hit
    forecast_cache.get("k2")  # miss
    s = forecast_cache.stats()
    assert s["hits"] == 1
    assert s["misses"] == 1
    assert s["entries"] == 1


def test_ttl_expiry(monkeypatch):
    monkeypatch.setattr(forecast_cache, "FORECAST_CACHE_TTL_SECONDS", 0)
    forecast_cache.set("k1", "v1")
    time.sleep(0.01)
    assert forecast_cache.get("k1") is None


def test_lru_eviction(monkeypatch):
    monkeypatch.setattr(forecast_cache, "FORECAST_CACHE_MAX_ENTRIES", 2)
    forecast_cache.set("k1", "v1")
    forecast_cache.set("k2", "v2")
    forecast_cache.set("k3", "v3")  # should evict k1 (least recently used)
    assert forecast_cache.get("k1") is None
    assert forecast_cache.get("k2") == "v2"
    assert forecast_cache.get("k3") == "v3"


def test_lru_access_updates_recency(monkeypatch):
    monkeypatch.setattr(forecast_cache, "FORECAST_CACHE_MAX_ENTRIES", 2)
    forecast_cache.set("k1", "v1")
    forecast_cache.set("k2", "v2")
    forecast_cache.get("k1")  # k1 is now most-recently-used
    forecast_cache.set("k3", "v3")  # should evict k2, not k1
    assert forecast_cache.get("k1") == "v1"
    assert forecast_cache.get("k2") is None
    assert forecast_cache.get("k3") == "v3"
