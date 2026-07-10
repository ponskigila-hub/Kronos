"""
Watchlist / favorites (item #8). Stored as a simple JSON file keyed by
user_id, so it works the same whether the caller is the CLI, Discord, or
WhatsApp (each platform passes its own user id as `user_id`).
"""
import json
import os
import threading

from .config import WATCHLIST_PATH

_lock = threading.Lock()


def _load():
    if not os.path.exists(WATCHLIST_PATH):
        return {}
    with open(WATCHLIST_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _save(data):
    with open(WATCHLIST_PATH, "w") as f:
        json.dump(data, f, indent=2)


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
