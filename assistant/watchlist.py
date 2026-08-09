"""
Watchlist / favorites (item #8). Stored as a simple JSON file keyed by
user_id, so it works the same whether the caller is the CLI, Discord, or
WhatsApp (each platform passes its own user id as `user_id`).

Persistence goes through assistant.storage, which makes every save atomic
(no corrupt half-written file on a crash) and keeps rotating backups with
automatic recovery if the main file is ever missing or unreadable --
see assistant/storage.py for details.
"""
import threading

from . import storage
from .config import WATCHLIST_PATH

_lock = threading.Lock()


def _load():
    return storage.load_json(WATCHLIST_PATH)


def _save(data):
    storage.save_json(WATCHLIST_PATH, data)


def add(user_id, ticker):
    ticker = ticker.upper()
    with _lock:
        data = _load()
        lst = data.setdefault(str(user_id), [])
        if ticker not in lst:
            lst.append(ticker)
        _save(data)
        return lst


def remove(user_id, ticker):
    ticker = ticker.upper()
    with _lock:
        data = _load()
        lst = data.setdefault(str(user_id), [])
        if ticker in lst:
            lst.remove(ticker)
        _save(data)
        return lst


def get(user_id):
    with _lock:
        data = _load()
        return data.get(str(user_id), [])


def clear(user_id):
    with _lock:
        data = _load()
        data[str(user_id)] = []
        _save(data)
        return []
