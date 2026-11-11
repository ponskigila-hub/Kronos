"""
SQLite persistence for Kronos.

Primary store for JSON documents that used to live only as files under
assistant_data/ (watchlist, simulation portfolios, screener history, notes…).

Schema is intentionally small: one key-value document table keyed by the
same path strings the rest of the app already uses (WATCHLIST_PATH, etc.).
That lets assistant.storage keep its public API while swapping the backend.

Normalized trading tables can be added later without breaking this layer.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional

from .config import DATABASE_PATH, DATA_DIR

_lock = threading.RLock()
_initialized = False


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DATABASE_PATH) or DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(migrate_json: bool = True) -> str:
    """Create tables (idempotent). Optionally import legacy JSON files once."""
    global _initialized
    with _lock:
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS kv_documents (
                    path        TEXT PRIMARY KEY,
                    payload     TEXT NOT NULL,
                    updated_at  REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                -- Optional normalized helpers (populated by higher-level code later)
                CREATE TABLE IF NOT EXISTS watchlist (
                    user_id   TEXT NOT NULL,
                    ticker    TEXT NOT NULL,
                    added_at  REAL NOT NULL,
                    PRIMARY KEY (user_id, ticker)
                );

                CREATE TABLE IF NOT EXISTS sim_accounts (
                    user_id      TEXT PRIMARY KEY,
                    starting_cash REAL NOT NULL,
                    cash         REAL NOT NULL,
                    created_at   REAL,
                    updated_at   REAL
                );

                CREATE TABLE IF NOT EXISTS sim_positions (
                    user_id   TEXT NOT NULL,
                    ticker    TEXT NOT NULL,
                    shares    REAL NOT NULL,
                    avg_cost  REAL NOT NULL,
                    meta_json TEXT,
                    PRIMARY KEY (user_id, ticker)
                );

                CREATE TABLE IF NOT EXISTS sim_trades (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id   TEXT NOT NULL,
                    ticker    TEXT NOT NULL,
                    side      TEXT NOT NULL,
                    shares    REAL NOT NULL,
                    price     REAL NOT NULL,
                    ts        REAL NOT NULL,
                    meta_json TEXT
                );

                CREATE TABLE IF NOT EXISTS forecast_performance (
                    ticker              TEXT PRIMARY KEY,
                    graded_count        INTEGER NOT NULL DEFAULT 0,
                    correct_direction   INTEGER NOT NULL DEFAULT 0,
                    avg_error_pct       REAL NOT NULL DEFAULT 0.0,
                    updated_at          REAL NOT NULL
                );
                """
            )
            conn.commit()
            if migrate_json:
                _migrate_legacy_json(conn)
            _initialized = True
        finally:
            conn.close()
    return DATABASE_PATH


def _migrate_legacy_json(conn: sqlite3.Connection) -> None:
    """One-time import of assistant_data/*.json into kv_documents if missing."""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", ("json_migrated_v1",)).fetchone()
    if row:
        return
    if not os.path.isdir(DATA_DIR):
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("json_migrated_v1", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        )
        conn.commit()
        return

    imported = 0
    for name in os.listdir(DATA_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(DATA_DIR, name)
        if not os.path.isfile(path):
            continue
        # Skip if already in DB
        exists = conn.execute(
            "SELECT 1 FROM kv_documents WHERE path = ?", (path,)
        ).fetchone()
        if exists:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        conn.execute(
            "INSERT OR REPLACE INTO kv_documents(path, payload, updated_at) VALUES (?, ?, ?)",
            (path, json.dumps(data), time.time()),
        )
        imported += 1
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (
            "json_migrated_v1",
            json.dumps({"at": time.time(), "imported": imported}),
        ),
    )
    conn.commit()


def ensure_db() -> None:
    if not _initialized:
        init_db(migrate_json=True)


def kv_get(path: str) -> Optional[Any]:
    ensure_db()
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT payload FROM kv_documents WHERE path = ?", (path,)
            ).fetchone()
            if not row:
                return None
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return None
        finally:
            conn.close()


def kv_set(path: str, data: Any) -> None:
    ensure_db()
    payload = json.dumps(data)
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO kv_documents(path, payload, updated_at) VALUES (?, ?, ?)",
                (path, payload, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def kv_delete(path: str) -> None:
    ensure_db()
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM kv_documents WHERE path = ?", (path,))
            conn.commit()
        finally:
            conn.close()


def kv_list_paths() -> list:
    ensure_db()
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT path, updated_at FROM kv_documents ORDER BY path"
            ).fetchall()
            return [{"path": r["path"], "updated_at": r["updated_at"]} for r in rows]
        finally:
            conn.close()


def record_forecast_grade(ticker: str, direction_correct: bool, error_pct: float) -> None:
    """Update rolling forecast-performance stats for a ticker after grading."""
    ensure_db()
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return
    try:
        error_pct = float(error_pct)
    except (TypeError, ValueError):
        error_pct = 0.0
    direction_correct = bool(direction_correct)
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            # Ensure table exists even if process initialized before this migration
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS forecast_performance (
                    ticker              TEXT PRIMARY KEY,
                    graded_count        INTEGER NOT NULL DEFAULT 0,
                    correct_direction   INTEGER NOT NULL DEFAULT 0,
                    avg_error_pct       REAL NOT NULL DEFAULT 0.0,
                    updated_at          REAL NOT NULL
                )
                """
            )
            row = conn.execute(
                "SELECT graded_count, correct_direction, avg_error_pct FROM forecast_performance WHERE ticker = ?",
                (ticker,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO forecast_performance
                        (ticker, graded_count, correct_direction, avg_error_pct, updated_at)
                    VALUES (?, 1, ?, ?, ?)
                    """,
                    (ticker, 1 if direction_correct else 0, error_pct, now),
                )
            else:
                n = int(row["graded_count"]) + 1
                correct = int(row["correct_direction"]) + (1 if direction_correct else 0)
                prev_avg = float(row["avg_error_pct"] or 0.0)
                avg = (prev_avg * (n - 1) + error_pct) / n
                conn.execute(
                    """
                    UPDATE forecast_performance
                    SET graded_count = ?, correct_direction = ?, avg_error_pct = ?, updated_at = ?
                    WHERE ticker = ?
                    """,
                    (n, correct, avg, now, ticker),
                )
            conn.commit()
        finally:
            conn.close()


def get_ticker_reliability(ticker: str):
    """Return rolling directional accuracy stats for a ticker, or None if unknown."""
    ensure_db()
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return None
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS forecast_performance (
                    ticker              TEXT PRIMARY KEY,
                    graded_count        INTEGER NOT NULL DEFAULT 0,
                    correct_direction   INTEGER NOT NULL DEFAULT 0,
                    avg_error_pct       REAL NOT NULL DEFAULT 0.0,
                    updated_at          REAL NOT NULL
                )
                """
            )
            row = conn.execute(
                "SELECT graded_count, correct_direction, avg_error_pct, updated_at "
                "FROM forecast_performance WHERE ticker = ?",
                (ticker,),
            ).fetchone()
            if row is None:
                return None
            n = int(row["graded_count"] or 0)
            correct = int(row["correct_direction"] or 0)
            accuracy = (correct / n * 100.0) if n > 0 else 0.0
            return {
                "ticker": ticker,
                "graded_count": n,
                "correct_direction": correct,
                "directional_accuracy": round(accuracy, 2),
                "avg_error_pct": round(float(row["avg_error_pct"] or 0.0), 4),
                "updated_at": float(row["updated_at"] or 0.0),
            }
        finally:
            conn.close()
