"""
Keeps enough state per user to support follow-up questions ("why is it
expected to decline?", "compare this with Microsoft") without the user
repeating themselves. Persisted to disk per user so context survives a
process restart (important for a Discord/WhatsApp bot).
"""
import json
import os
import threading

from .config import CONVERSATION_DIR

_locks = {}


def _lock_for(user_id):
    _locks.setdefault(user_id, threading.Lock())
    return _locks[user_id]


class ConversationContext:
    def __init__(self, user_id):
        self.user_id = str(user_id)
        self.last_tickers = []
        self.last_forecast = None      # small serializable summary, not the full DataFrame
        self.last_explanation = None
        self.history = []              # list of {"role": "user"/"assistant", "text": ...}
        self.beginner_mode = False     # explanation register -- see assistant.nlp.detect_mode
        self._path = os.path.join(CONVERSATION_DIR, f"{self.user_id}.json")
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    data = json.load(f)
                self.last_tickers = data.get("last_tickers", [])
                self.last_forecast = data.get("last_forecast")
                self.last_explanation = data.get("last_explanation")
                self.history = data.get("history", [])[-20:]
                self.beginner_mode = data.get("beginner_mode", False)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        with _lock_for(self.user_id):
            with open(self._path, "w") as f:
                json.dump({
                    "last_tickers": self.last_tickers,
                    "last_forecast": self.last_forecast,
                    "last_explanation": self.last_explanation,
                    "history": self.history[-20:],
                    "beginner_mode": self.beginner_mode,
                }, f, indent=2, default=str)

    def remember_turn(self, user_text, assistant_text):
        self.history.append({"role": "user", "text": user_text})
        self.history.append({"role": "assistant", "text": assistant_text})
        self.history = self.history[-20:]

    def update_forecast(self, tickers, forecast_summary, explanation_text):
        self.last_tickers = tickers
        self.last_forecast = forecast_summary
        self.last_explanation = explanation_text


_contexts = {}
_ctx_lock = threading.Lock()


def get_context(user_id):
    with _ctx_lock:
        if user_id not in _contexts:
            _contexts[user_id] = ConversationContext(user_id)
        return _contexts[user_id]
