"""
Tests for webapp/jobs.py's JobManager -- submit/poll lifecycle, error
handling, TTL sweeping. Pure in-process logic, no Flask app needed.
"""
import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))
from jobs import JobManager


def test_submit_and_poll_success():
    jm = JobManager()
    job_id = jm.submit(lambda x: x * 2, 21)
    # Poll until done (background thread needs a moment).
    for _ in range(50):
        status = jm.poll(job_id)
        if status["status"] != "pending":
            break
        time.sleep(0.01)
    assert status["status"] == "done"
    assert status["result"] == 42


def test_poll_unknown_job_returns_not_found():
    jm = JobManager()
    assert jm.poll("not-a-real-id")["status"] == "not_found"


def test_submit_with_exception_reports_error():
    jm = JobManager()

    def boom():
        raise RuntimeError("kaboom")

    job_id = jm.submit(boom)
    for _ in range(50):
        status = jm.poll(job_id)
        if status["status"] != "pending":
            break
        time.sleep(0.01)
    assert status["status"] == "error"
    assert "kaboom" in status["error"]


def test_submit_passes_args_and_kwargs():
    jm = JobManager()
    job_id = jm.submit(lambda a, b, c=None: (a, b, c), 1, 2, c=3)
    for _ in range(50):
        status = jm.poll(job_id)
        if status["status"] != "pending":
            break
        time.sleep(0.01)
    assert status["result"] == (1, 2, 3)


def test_get_result_returns_none_when_not_done():
    jm = JobManager()
    assert jm.get_result("nonexistent") is None

    def slow():
        time.sleep(0.2)
        return "eventually"

    job_id = jm.submit(slow)
    assert jm.get_result(job_id) is None  # still pending
    for _ in range(50):
        if jm.get_result(job_id) is not None:
            break
        time.sleep(0.01)
    assert jm.get_result(job_id) == "eventually"


def test_get_result_returns_none_for_errored_job():
    jm = JobManager()

    def boom():
        raise ValueError("nope")

    job_id = jm.submit(boom)
    for _ in range(50):
        if jm.poll(job_id)["status"] != "pending":
            break
        time.sleep(0.01)
    assert jm.get_result(job_id) is None


def test_sweep_removes_old_completed_jobs():
    jm = JobManager(ttl_seconds=0)
    job_id = jm.submit(lambda: "done")
    for _ in range(50):
        if jm.poll(job_id)["status"] != "pending":
            break
        time.sleep(0.01)
    assert jm.poll(job_id)["status"] == "done"

    time.sleep(0.01)
    jm.submit(lambda: "trigger a sweep")  # sweeping happens on the next submit
    assert jm.poll(job_id)["status"] == "not_found"


def test_many_concurrent_jobs_get_distinct_ids():
    jm = JobManager()
    ids = [jm.submit(lambda i=i: i, i) for i in range(20)]
    assert len(set(ids)) == 20  # all unique
    for jid in ids:
        for _ in range(50):
            if jm.poll(jid)["status"] != "pending":
                break
            time.sleep(0.01)
    results = sorted(jm.poll(jid)["result"] for jid in ids)
    assert results == list(range(20))
