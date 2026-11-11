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

                CREATE TABLE IF NOT EXISTS forecast_grades (
                    position_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    horizon_days INTEGER NOT NULL,
                    predicted_return REAL NOT NULL,
                    actual_return REAL NOT NULL,
                    direction_correct INTEGER NOT NULL,
                    error_pct REAL NOT NULL,
                    graded_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_forecast_grades_ticker
                    ON forecast_grades(ticker);
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


def record_forecast_grade(position_id: str, user_id: str, ticker: str,
                          horizon_days: int, predicted_return: float,
                          actual_return: float, direction_correct: bool,
                          error_pct: float, graded_at: Optional[float] = None) -> bool:
    """Persist one forward-paper-trade grade; returns False for duplicates.

    Return fields are decimal returns (0.05 = 5%); error_pct is the absolute
    forecast error in percentage points, matching simulation grade output.
    The position id is the idempotency key so repeated portfolio reads cannot
    double-count the same matured forecast.
    """
    ensure_db()
    values = (str(position_id), str(user_id), str(ticker).upper(), int(horizon_days),
              float(predicted_return), float(actual_return), int(bool(direction_correct)),
              float(error_pct), float(graded_at if graded_at is not None else time.time()))
    with _lock:
        conn = _connect()
        try:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO forecast_grades
                   (position_id,user_id,ticker,horizon_days,predicted_return,actual_return,
                    direction_correct,error_pct,graded_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                values,
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()


def get_forecast_grade_summary(ticker: Optional[str] = None) -> dict:
    """Aggregate saved forward-grade outcomes, overall or for one ticker."""
    ensure_db()
    clause = " WHERE ticker = ?" if ticker else ""
    params = (str(ticker).upper(),) if ticker else ()
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                """SELECT COUNT(*) AS n, AVG(direction_correct) AS direction_accuracy,
                          AVG(error_pct) AS mean_absolute_error_pct,
                          AVG(predicted_return) AS mean_predicted_return,
                          AVG(actual_return) AS mean_actual_return
                   FROM forecast_grades""" + clause, params,
            ).fetchone()
            return {
                "ticker": str(ticker).upper() if ticker else None,
                "count": int(row["n"] or 0),
                "direction_accuracy_pct": (round(float(row["direction_accuracy"]) * 100, 2)
                                            if row["direction_accuracy"] is not None else None),
                "mean_absolute_error_pct": (round(float(row["mean_absolute_error_pct"]), 4)
                                            if row["mean_absolute_error_pct"] is not None else None),
                "mean_predicted_return": (float(row["mean_predicted_return"])
                                          if row["mean_predicted_return"] is not None else None),
                "mean_actual_return": (float(row["mean_actual_return"])
                                       if row["mean_actual_return"] is not None else None),
            }
        finally:
            conn.close()


def get_ticker_reliability(ticker: str, horizon_days: Optional[int] = None,
                           user_id: Optional[str] = None) -> Optional[dict]:
    """Return deduplicated historical grades for one ticker.

    Uses the position-keyed source table (not a second counter table), and can
    scope results by user and forecast horizon. `directional_accuracy` is in
    percent points (0–100); the result is descriptive, not a calibrated skill
    estimate.
    """
    ensure_db()
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return None
    clauses = ["ticker = ?"]
    params = [ticker]
    if horizon_days is not None:
        clauses.append("horizon_days = ?")
        params.append(int(horizon_days))
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(str(user_id))
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                """SELECT COUNT(*) AS n, SUM(direction_correct) AS correct,
                          AVG(error_pct) AS avg_error, MAX(graded_at) AS updated_at
                   FROM forecast_grades WHERE """ + " AND ".join(clauses),
                tuple(params),
            ).fetchone()
            count = int(row["n"] or 0)
            if count == 0:
                return None
            return {
                "ticker": ticker,
                "graded_count": count,
                "correct_direction": int(row["correct"] or 0),
                "directional_accuracy": round(float(row["correct"] or 0) / count * 100.0, 2),
                "avg_error_pct": round(float(row["avg_error"] or 0.0), 4),
                "updated_at": float(row["updated_at"] or 0.0),
                "horizon_days": int(horizon_days) if horizon_days is not None else None,
            }
        finally:
            conn.close()
