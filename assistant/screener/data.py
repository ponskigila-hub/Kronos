"""
Concurrent, disk-cached OHLCV downloads for the screener.

Reuses assistant.data_fetcher.fetch_history (the same validated, cleaned
pipeline the forecaster/backtester use) for each individual ticker, but
adds what a 30-500-ticker screen needs on top of it:
  - a disk cache (assistant_data/screener_cache/) so re-running a screen
    within the same session/day doesn't re-download tickers you already
    have -- keyed by ticker + lookback_days, expires after
    SCREENER_CONFIG["cache_ttl_minutes"]
  - a thread pool so tickers download concurrently instead of one at a time
  - per-ticker error isolation -- one bad/delisted ticker never aborts the
    whole screen, it's just recorded as a failure and skipped
"""
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from .. import data_fetcher
from ..config import SCREENER_CACHE_DIR, SCREENER_CONFIG

_cache_lock = threading.Lock()


def _cache_path(ticker, lookback_days):
    safe = ticker.replace("/", "_")
    return os.path.join(SCREENER_CACHE_DIR, f"{safe}_{lookback_days}.csv")


def _read_cache(ticker, lookback_days, ttl_minutes):
    path = _cache_path(ticker, lookback_days)
    if not os.path.exists(path):
        return None
    age_minutes = (time.time() - os.path.getmtime(path)) / 60
    if age_minutes > ttl_minutes:
        return None
    try:
        df = pd.read_csv(path, parse_dates=["timestamps"])
        if df.empty:
            return None
        return df
    except Exception:
        return None


def _write_cache(ticker, lookback_days, df):
    try:
        with _cache_lock:
            df.to_csv(_cache_path(ticker, lookback_days), index=False)
    except OSError:
        pass  # cache is purely a speed optimization -- never let it break a screen


def fetch_one(ticker, lookback_days=None, ttl_minutes=None, use_cache=True):
    """Fetch (and cache) a single ticker's history. Raises whatever
    data_fetcher.fetch_history raises on failure -- callers in this module
    catch it; callers reusing this directly should too."""
    lookback_days = lookback_days or SCREENER_CONFIG["lookback_days"]
    ttl_minutes = SCREENER_CONFIG["cache_ttl_minutes"] if ttl_minutes is None else ttl_minutes

    if use_cache:
        cached = _read_cache(ticker, lookback_days, ttl_minutes)
        if cached is not None:
            return cached

    df = data_fetcher.fetch_history(ticker, lookback_days=lookback_days)
    if use_cache:
        _write_cache(ticker, lookback_days, df)
    return df


def fetch_universe(tickers, lookback_days=None, max_workers=None, progress_cb=None, use_cache=True):
    """
    Download history for every ticker in `tickers` concurrently.

    Returns (results, failures):
        results:  {ticker: DataFrame}
        failures: {ticker: str(error)}

    progress_cb(done, total, ticker) is called after each ticker finishes
    (success or failure) -- used by the web app to show scan progress.
    """
    lookback_days = lookback_days or SCREENER_CONFIG["lookback_days"]
    max_workers = max_workers or SCREENER_CONFIG["max_workers"]

    results, failures = {}, {}
    total = len(tickers)
    done = 0
    done_lock = threading.Lock()

    def _job(t):
        return t, fetch_one(t, lookback_days=lookback_days, use_cache=use_cache)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_job, t): t for t in tickers}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                ticker, df = fut.result()
                results[ticker] = df
            except Exception as e:
                failures[t] = str(e)
            finally:
                with done_lock:
                    done += 1
                    d = done
                if progress_cb:
                    try:
                        progress_cb(d, total, t)
                    except Exception:
                        pass

    return results, failures
