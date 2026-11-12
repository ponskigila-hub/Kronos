"""
Per-user conversation context + multi-session chat history.

Each user has:
  - active session (messages, mode, title)
  - list of past sessions (for Gemini-style history sidebar)

Persisted under CONVERSATION_DIR so context survives restarts.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from .config import CONVERSATION_DIR

_locks: dict = {}
_contexts: dict = {}
_ctx_lock = threading.Lock()


def _lock_for(user_id):
    _locks.setdefault(user_id, threading.Lock())
    return _locks[user_id]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day_label(iso_or_ts) -> str:
    """Human day bucket: Today / Yesterday / Mon, 12 Nov 2026."""
    try:
        if isinstance(iso_or_ts, (int, float)):
            dt = datetime.fromtimestamp(iso_or_ts, tz=timezone.utc)
        else:
            s = str(iso_or_ts).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return "Earlier"
    now = datetime.now(timezone.utc)
    d0 = now.date()
    d1 = dt.date()
    delta = (d0 - d1).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return dt.strftime("%a, %d %b %Y")


class ConversationContext:
    def __init__(self, user_id):
        self.user_id = str(user_id)
        self.last_tickers = []
        self.last_forecast = None
        self.last_explanation = None
        self.last_intent = None
        self.last_topic = None
        self.history = []  # active session messages
        self.beginner_mode = True
        self.active_session_id = None
        self.sessions = []  # [{id, title, created_at, updated_at, history, beginner_mode}]
        self._path = os.path.join(CONVERSATION_DIR, f"{self.user_id}.json")
        self._load()
        if not self.active_session_id:
            self.new_session(title="New chat", persist=False)
            self.save()

    def _load(self):
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        self.last_tickers = data.get("last_tickers", [])
        self.last_forecast = data.get("last_forecast")
        self.last_explanation = data.get("last_explanation")
        self.last_intent = data.get("last_intent")
        self.last_topic = data.get("last_topic")
        self.beginner_mode = data.get("beginner_mode", True)
        self.sessions = data.get("sessions") or []
        self.active_session_id = data.get("active_session_id")
        # Migrate legacy single history → one session
        legacy = data.get("history") or []
        if not self.sessions and legacy:
            sid = uuid.uuid4().hex[:12]
            self.sessions = [{
                "id": sid,
                "title": self._title_from_history(legacy) or "Earlier chat",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "history": legacy[-40:],
                "beginner_mode": self.beginner_mode,
            }]
            self.active_session_id = sid
        if self.active_session_id:
            sess = self._find(self.active_session_id)
            if sess:
                self.history = list(sess.get("history") or [])
                self.beginner_mode = sess.get("beginner_mode", self.beginner_mode)
            else:
                self.active_session_id = None

    def _find(self, session_id):
        for s in self.sessions:
            if s.get("id") == session_id:
                return s
        return None

    @staticmethod
    def _title_from_history(history) -> str:
        for m in history or []:
            if m.get("role") == "user" and (m.get("text") or "").strip():
                t = m["text"].strip().replace("\n", " ")
                return (t[:48] + "…") if len(t) > 48 else t
        return "New chat"

    def _sync_active_into_sessions(self):
        if not self.active_session_id:
            return
        sess = self._find(self.active_session_id)
        if not sess:
            return
        sess["history"] = list(self.history[-40:])
        sess["beginner_mode"] = self.beginner_mode
        sess["updated_at"] = _now_iso()
        if not sess.get("title") or sess.get("title") in ("New chat", "Earlier chat"):
            sess["title"] = self._title_from_history(self.history) or sess.get("title") or "New chat"

    def save(self):
        self._sync_active_into_sessions()
        os.makedirs(CONVERSATION_DIR, exist_ok=True)
        with _lock_for(self.user_id):
            with open(self._path, "w") as f:
                json.dump({
                    "last_tickers": self.last_tickers,
                    "last_forecast": self.last_forecast,
                    "last_explanation": self.last_explanation,
                    "last_intent": self.last_intent,
                    "last_topic": self.last_topic,
                    "history": self.history[-40:],
                    "beginner_mode": self.beginner_mode,
                    "active_session_id": self.active_session_id,
                    "sessions": self.sessions[-50:],
                }, f, indent=2, default=str)

    def new_session(self, title: str = "New chat", persist: bool = True):
        self._sync_active_into_sessions()
        sid = uuid.uuid4().hex[:12]
        sess = {
            "id": sid,
            "title": title or "New chat",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "history": [],
            "beginner_mode": self.beginner_mode,
        }
        self.sessions.insert(0, sess)
        self.sessions = self.sessions[:50]
        self.active_session_id = sid
        self.history = []
        self.last_tickers = []
        self.last_forecast = None
        self.last_explanation = None
        self.last_intent = None
        self.last_topic = None
        if persist:
            self.save()
        return sess

    def switch_session(self, session_id: str) -> bool:
        self._sync_active_into_sessions()
        sess = self._find(session_id)
        if not sess:
            return False
        self.active_session_id = session_id
        self.history = list(sess.get("history") or [])
        self.beginner_mode = sess.get("beginner_mode", True)
        self.save()
        return True

    def list_sessions_grouped(self):
        self._sync_active_into_sessions()
        groups = {}
        order = []
        for s in self.sessions:
            label = _day_label(s.get("updated_at") or s.get("created_at"))
            if label not in groups:
                groups[label] = []
                order.append(label)
            groups[label].append({
                "id": s["id"],
                "title": s.get("title") or "Chat",
                "updated_at": s.get("updated_at"),
                "active": s["id"] == self.active_session_id,
                "message_count": len(s.get("history") or []),
            })
        return [{"label": lab, "sessions": groups[lab]} for lab in order]

    def remember_turn(self, user_text, assistant_text):
        self.history.append({"role": "user", "text": user_text, "ts": _now_iso()})
        self.history.append({"role": "assistant", "text": assistant_text, "ts": _now_iso()})
        self.history = self.history[-40:]
        self._sync_active_into_sessions()

    def update_forecast(self, tickers, forecast_summary, explanation_text):
        self.last_tickers = tickers
        self.last_forecast = forecast_summary
        self.last_explanation = explanation_text
        self.last_topic = tickers[0] if tickers else self.last_topic
        self.last_intent = "forecast"

    def remember_topic(self, intent, topic=None):
        self.last_intent = intent
        self.last_topic = topic or self.last_topic


def get_context(user_id):
    with _ctx_lock:
        if user_id not in _contexts:
            _contexts[user_id] = ConversationContext(user_id)
        return _contexts[user_id]
