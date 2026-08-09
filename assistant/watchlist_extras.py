"""
Two small JSON-backed stores, keyed by user_id then ticker, following the
exact same pattern as assistant/watchlist.py:
  - notes: free-text notes about a company ("waiting on their EV rollout",
    "thesis: margin expansion from AI chips", etc.)
  - entry_zones: a buy-range the user has set for themselves (low/high
    price), so the UI can flag when the current price is inside it.

Both are personal annotations, not analysis -- nothing here calls Kronos or
does any calculation beyond the entry-zone in/out check.

Persistence goes through assistant.storage (atomic writes + rotating
backups with automatic recovery) -- see assistant/storage.py.
"""
import threading

from . import storage
from .config import WATCHLIST_NOTES_PATH, WATCHLIST_ENTRY_ZONES_PATH

_lock = threading.Lock()


def _load(path):
    return storage.load_json(path)


def _save(path, data):
    storage.save_json(path, data)


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
def get_note(user_id, ticker):
    with _lock:
        data = _load(WATCHLIST_NOTES_PATH)
        return data.get(str(user_id), {}).get(ticker.upper(), "")


def get_all_notes(user_id):
    with _lock:
        data = _load(WATCHLIST_NOTES_PATH)
        return data.get(str(user_id), {})


def set_note(user_id, ticker, text):
    ticker = ticker.upper()
    with _lock:
        data = _load(WATCHLIST_NOTES_PATH)
        user_notes = data.setdefault(str(user_id), {})
        if text and text.strip():
            user_notes[ticker] = text.strip()
        else:
            user_notes.pop(ticker, None)  # empty note = clear it
        _save(WATCHLIST_NOTES_PATH, data)
        return user_notes.get(ticker, "")


# ---------------------------------------------------------------------------
# Entry zones (buy range)
# ---------------------------------------------------------------------------
def get_entry_zone(user_id, ticker):
    """Returns {"low": float, "high": float} or None if unset."""
    with _lock:
        data = _load(WATCHLIST_ENTRY_ZONES_PATH)
        return data.get(str(user_id), {}).get(ticker.upper())


def get_all_entry_zones(user_id):
    with _lock:
        data = _load(WATCHLIST_ENTRY_ZONES_PATH)
        return data.get(str(user_id), {})


def set_entry_zone(user_id, ticker, low, high):
    ticker = ticker.upper()
    low, high = float(low), float(high)
    if low > high:
        low, high = high, low
    with _lock:
        data = _load(WATCHLIST_ENTRY_ZONES_PATH)
        user_zones = data.setdefault(str(user_id), {})
        user_zones[ticker] = {"low": low, "high": high}
        _save(WATCHLIST_ENTRY_ZONES_PATH, data)
        return user_zones[ticker]


def clear_entry_zone(user_id, ticker):
    ticker = ticker.upper()
    with _lock:
        data = _load(WATCHLIST_ENTRY_ZONES_PATH)
        user_zones = data.setdefault(str(user_id), {})
        user_zones.pop(ticker, None)
        _save(WATCHLIST_ENTRY_ZONES_PATH, data)


def check_zone_status(price, zone):
    """price: float. zone: {"low","high"} or None. Returns 'in' / 'below' / 'above' / None."""
    if zone is None or price is None:
        return None
    if price < zone["low"]:
        return "below"
    if price > zone["high"]:
        return "above"
    return "in"
