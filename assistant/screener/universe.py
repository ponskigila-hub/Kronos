"""
Universe providers -- each returns a plain, deduplicated list of ticker
symbols. Kept deliberately dumb (no scoring, no data download) so new
universes are easy to add without touching the rest of the screener.

S&P 500 / NASDAQ-100 / Dow 30 try a live refresh from Wikipedia first
(cached on disk for SCREENER_CONFIG["cache_ttl_minutes"] * 24, i.e. reused
for about a day so we don't hammer Wikipedia on every screen), and fall
back to the bundled snapshot files in screener/data/ if that fails for any
reason (no internet, page layout changed, parser dependency missing) --
this always keeps the screener usable, just possibly with a slightly
stale/reduced universe when offline.
"""
import json
import os
import time

from ..config import SCREENER_CACHE_DIR
from ..watchlist import get as _get_watchlist_tickers

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_HERE, "data")

_WIKI_SOURCES = {
    "sp500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
    "nasdaq100": ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"),
    "dow30": ("https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average", "Symbol"),
}
_LIVE_CACHE_TTL_SECONDS = 24 * 60 * 60  # refresh at most once a day


def _read_snapshot(filename):
    path = os.path.join(_DATA_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [
            line.strip().upper().replace(".", "-")  # BRK.B -> BRK-B (yfinance style)
            for line in f
            if line.strip() and not line.startswith("#")
        ]


def _live_cache_path(key):
    return os.path.join(SCREENER_CACHE_DIR, f"universe_{key}.json")


def _load_live_cache(key):
    path = _live_cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
        if time.time() - payload.get("fetched_at", 0) > _LIVE_CACHE_TTL_SECONDS:
            return None
        return payload.get("tickers") or None
    except (json.JSONDecodeError, OSError):
        return None


def _save_live_cache(key, tickers):
    try:
        with open(_live_cache_path(key), "w") as f:
            json.dump({"fetched_at": time.time(), "tickers": tickers}, f)
    except OSError:
        pass


def _fetch_live(key):
    """Best-effort live refresh via Wikipedia. Returns None on any failure
    (missing lxml, no internet, page layout changed) so the caller falls
    back to the bundled snapshot -- this must never raise."""
    url, symbol_col = _WIKI_SOURCES[key]
    try:
        import pandas as pd
        tables = pd.read_html(url)
        for table in tables:
            cols = {str(c).strip(): c for c in table.columns}
            if symbol_col in cols:
                tickers = [
                    str(v).strip().upper().replace(".", "-")
                    for v in table[cols[symbol_col]].tolist()
                    if str(v).strip() and str(v).strip().lower() != "nan"
                ]
                if len(tickers) >= 10:  # sanity check -- a real index table, not a stray small one
                    return tickers
        return None
    except Exception:
        return None


def _resolve(key, snapshot_filename):
    cached = _load_live_cache(key)
    if cached:
        return cached
    live = _fetch_live(key)
    if live:
        _save_live_cache(key, live)
        return live
    return _read_snapshot(snapshot_filename)


def sp500():
    return _resolve("sp500", "sp500_fallback.txt")


def nasdaq100():
    return _resolve("nasdaq100", "nasdaq100.txt")


def dow30():
    return _resolve("dow30", "dow30.txt")


def watchlist(user_id="default"):
    return [t.upper() for t in _get_watchlist_tickers(user_id)]


def custom(text):
    """Parse a free-typed comma/whitespace/newline separated ticker list."""
    if not text:
        return []
    raw = text.replace(",", " ").replace("\n", " ").replace("\t", " ").split()
    seen, out = set(), []
    for t in raw:
        t = t.strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def from_csv_rows(rows):
    """rows: list of dict (e.g. from csv.DictReader). Looks for a 'ticker'
    or 'symbol' column (case-insensitive); falls back to the first column
    if neither is present."""
    out, seen = [], set()
    for row in rows:
        val = None
        for key in row:
            if key and str(key).strip().lower() in ("ticker", "symbol"):
                val = row[key]
                break
        if val is None and row:
            val = list(row.values())[0]
        if val:
            t = str(val).strip().upper()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


UNIVERSES = {
    "sp500": "S&P 500",
    "nasdaq100": "NASDAQ-100",
    "dow30": "Dow Jones 30",
    "watchlist": "My Watchlist",
}


def resolve_universe(key, user_id="default", custom_text=None, csv_rows=None):
    """Single dispatch point used by the web app / engine."""
    if key == "sp500":
        return sp500()
    if key == "nasdaq100":
        return nasdaq100()
    if key == "dow30":
        return dow30()
    if key == "watchlist":
        return watchlist(user_id)
    if key == "custom":
        return custom(custom_text or "")
    if key == "csv":
        return from_csv_rows(csv_rows or [])
    raise ValueError(f"Unknown universe '{key}'.")
