"""
Tests for assistant/screener/history.py -- uses an in-memory fake for
assistant.storage (not a temp file) so these tests can't touch the real
assistant_data/ directory at all. This matters here specifically: this
module's storage.load_json/save_json recover from backups by matching
filename inside the one global BACKUP_DIR (assistant_data/backups/), not
by full path -- so pointing SCREENER_HISTORY_PATH at a pytest tmp_path
alone does NOT isolate a test from real backups left by a previous run
(or from writing new ones into the real directory). Faking storage
itself sidesteps that entirely.
"""
import pytest

from assistant.screener import history


def _fake_result(tickers):
    return {
        "universe_size": 500,
        "kronos_ran": True,
        "elapsed_seconds": 12.3,
        "quality_summary": {"scanned": 500, "ranked": len(tickers)},
        "rows": [
            {"rank": i + 1, "ticker": t, "price": 100.0 + i, "overall_score": 90.0 - i, "signal": "Candidate"}
            for i, t in enumerate(tickers)
        ],
    }


class _FakeStorage:
    """In-memory stand-in for assistant.storage's load_json/save_json,
    keyed by path exactly like the real thing but with zero filesystem
    or backup-directory side effects."""
    def __init__(self):
        self.data = {}

    def load_json(self, path):
        return self.data.get(path, {})

    def save_json(self, path, data):
        self.data[path] = data


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr(history, "_load", lambda: fake.load_json("screener_history_test"))
    monkeypatch.setattr(history, "_save", lambda data: fake.save_json("screener_history_test", data))
    yield fake


def test_record_and_get_history_roundtrip():
    entry = history.record_run("user1", _fake_result(["AAPL", "MSFT"]), "sp500", "momentum")
    hist = history.get_history("user1")
    assert len(hist) == 1
    assert hist[0]["id"] == entry["id"]
    assert [t["ticker"] for t in hist[0]["tickers"]] == ["AAPL", "MSFT"]
    assert hist[0]["universe"] == "sp500"
    assert hist[0]["preset"] == "momentum"


def test_history_is_newest_first():
    history.record_run("user1", _fake_result(["AAPL"]), "sp500", "none")
    second = history.record_run("user1", _fake_result(["MSFT"]), "nasdaq100", "none")
    hist = history.get_history("user1")
    assert hist[0]["id"] == second["id"]  # most recent run comes first


def test_history_is_isolated_per_user():
    history.record_run("user1", _fake_result(["AAPL"]), "sp500", "none")
    history.record_run("user2", _fake_result(["TSLA"]), "sp500", "none")
    assert [t["ticker"] for t in history.get_history("user1")[0]["tickers"]] == ["AAPL"]
    assert [t["ticker"] for t in history.get_history("user2")[0]["tickers"]] == ["TSLA"]


def test_history_respects_max_runs_cap(monkeypatch):
    monkeypatch.setattr(history, "SCREENER_HISTORY_MAX_RUNS", 3)
    for i in range(5):
        history.record_run("user1", _fake_result([f"T{i}"]), "sp500", "none")
    hist = history.get_history("user1")
    assert len(hist) == 3
    # The 3 most recent runs (T4, T3, T2) should survive, oldest evicted.
    assert [h["tickers"][0]["ticker"] for h in hist] == ["T4", "T3", "T2"]


def test_get_history_limit_param():
    for i in range(5):
        history.record_run("user1", _fake_result([f"T{i}"]), "sp500", "none")
    assert len(history.get_history("user1", limit=2)) == 2


def test_get_run_by_id():
    entry = history.record_run("user1", _fake_result(["AAPL"]), "sp500", "none")
    found = history.get_run("user1", entry["id"])
    assert found is not None
    assert found["id"] == entry["id"]
    assert history.get_run("user1", "not-a-real-id") is None


def test_clear_history():
    history.record_run("user1", _fake_result(["AAPL"]), "sp500", "none")
    assert len(history.get_history("user1")) == 1
    history.clear_history("user1")
    assert history.get_history("user1") == []


def test_empty_rows_produces_empty_tickers_list():
    entry = history.record_run("user1", _fake_result([]), "sp500", "none")
    assert entry["tickers"] == []


def test_ticker_appearance_count():
    history.record_run("user1", _fake_result(["AAPL", "MSFT"]), "sp500", "momentum")
    history.record_run("user1", _fake_result(["AAPL"]), "nasdaq100", "value")
    history.record_run("user1", _fake_result(["MSFT"]), "sp500", "momentum")

    appearances = history.ticker_appearance_count("user1", "aapl")  # case-insensitive
    assert len(appearances) == 2
    assert all("rank" in a and "score" in a for a in appearances)
