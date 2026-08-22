"""
In-process prediction cache for Kronos forecasts.

Problem: every chat turn that touches a forecast (`forecast AAPL`, then
`why`, then `what are the risks`, then a follow-up chart) currently calls
`forecaster.run_forecast()` again from scratch, even though the underlying
market data and parameters haven't changed. Kronos inference is by far the
most expensive step in the pipeline, so this is the single highest-impact
place to avoid repeated work.

Design goals (kept intentionally simple -- see project brief: "prefer the
simplest reliable solution", "do not add Redis unless genuinely necessary"):

  - In-memory, per-process. This app runs as a single Flask process (or a
    single CLI/bot process) per the deployment doc, so a process-local cache
    is sufficient and avoids adding infrastructure.
  - TTL-based expiry, so a cached forecast can't go stale forever even if a
    key were to collide (e.g. process left running for days on a rarely
    updated ticker).
  - LRU eviction with a hard cap on entry count, so memory can't grow
    unbounded across a long-running process touching many tickers.
  - Thread-safe: the web app parallelizes I/O with ThreadPoolExecutor and
    Flask itself is multi-threaded, so multiple requests can race here.
  - The cache key is derived from the *actual data fed to the model*
    (a content hash of the history window actually used, not just a ticker
    string) plus every parameter that affects the model's output. This is
    strictly correct: if the same ticker/timeframe/lookback/horizon/model
    combination is requested again before new market data has arrived, the
    input to Kronos is byte-identical and the cached output is exactly what
    a fresh call would have produced -- not an approximation.
"""
import hashlib
import threading
import time
from collections import OrderedDict

import pandas as pd

from .config import (
    FORECAST_CACHE_TTL_SECONDS,
    FORECAST_CACHE_MAX_ENTRIES,
    KRONOS_MODEL_ID,
)

_lock = threading.Lock()
_store = OrderedDict()  # key -> (expires_at, value)

_hits = 0
_misses = 0


def make_key(x_df, x_timestamp, pred_len, n_runs, lookback, T, top_p,
             sample_count, anchor_to_last_close):
    """
    Build a stable fingerprint of everything that determines Kronos's
    output: the exact history window fed to the model (via a vectorized
    pandas content hash, not just the last row -- two different windows
    that happen to share a last close/timestamp must not collide) plus
    every sampling parameter and the active model id (so switching
    KRONOS_MODEL_ID automatically invalidates old entries instead of
    silently serving forecasts from a different model).
    """
    data_hash = hashlib.md5(
        pd.util.hash_pandas_object(x_df, index=False).values.tobytes()
    ).hexdigest()
    ts_hash = hashlib.md5(
        pd.util.hash_pandas_object(x_timestamp, index=False).values.tobytes()
    ).hexdigest()
    parts = (
        KRONOS_MODEL_ID, data_hash, ts_hash,
        int(pred_len), int(n_runs), int(lookback),
        round(float(T), 4), round(float(top_p), 4), int(sample_count),
        bool(anchor_to_last_close),
    )
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


def get(key):
    global _hits, _misses
    with _lock:
        entry = _store.get(key)
        if entry is None:
            _misses += 1
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            del _store[key]
            _misses += 1
            return None
        _store.move_to_end(key)  # mark as recently used
        _hits += 1
        return value


def set(key, value):
    with _lock:
        _store[key] = (time.time() + FORECAST_CACHE_TTL_SECONDS, value)
        _store.move_to_end(key)
        while len(_store) > FORECAST_CACHE_MAX_ENTRIES:
            _store.popitem(last=False)  # evict least-recently-used


def clear():
    """Mainly for tests / a manual admin action."""
    global _hits, _misses
    with _lock:
        _store.clear()
        _hits = 0
        _misses = 0


def stats():
    with _lock:
        total = _hits + _misses
        return {
            "entries": len(_store),
            "max_entries": FORECAST_CACHE_MAX_ENTRIES,
            "ttl_seconds": FORECAST_CACHE_TTL_SECONDS,
            "hits": _hits,
            "misses": _misses,
            "hit_rate": round(_hits / total, 3) if total else None,
        }
