"""
Generic background-job + polling helper.

Several routes in this app kick off real Kronos inference (a walk-forward
backtest, a screener run with Kronos enabled, a demo-trade buy that
snapshots a forecast) that can legitimately take anywhere from several
seconds to a few minutes depending on model size and hardware. Tying that
work to the lifetime of one HTTP request means the browser just sits on
a spinner with no feedback, and on slower hardware can hit a request
timeout entirely.

JobManager turns "run this slow function" into: submit it, get a job id
back immediately, poll for the result. This is the same pattern the chat
and manual-forecast routes in webapp/app.py already used before this file
existed (each with its own hand-rolled job dict/lock/sweep) -- this is
that pattern extracted once so every new slow route reuses it instead of
copy-pasting it again.

In-memory only, single-process -- consistent with this app's deployment
model (see DEPLOYMENT.md). A job still in flight is dropped if the server
restarts, same as any other in-memory state here. Requires the dev server
to run with threaded=True (already the case -- see the bottom of
webapp/app.py) so a poll request isn't blocked behind a worker thread.
"""
import threading
import time
import uuid


class JobManager:
    def __init__(self, ttl_seconds=30 * 60):
        self._jobs = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds

    def _sweep_locked(self):
        cutoff = time.time() - self._ttl_seconds
        stale = [jid for jid, j in self._jobs.items()
                 if j["status"] != "pending" and j["created"] < cutoff]
        for jid in stale:
            self._jobs.pop(jid, None)

    def submit(self, fn, *args, **kwargs):
        """Run fn(*args, **kwargs) in a background thread. Returns the new
        job id immediately -- the caller should return that to the client
        right away rather than waiting on it."""
        job_id = uuid.uuid4().hex
        with self._lock:
            self._sweep_locked()
            self._jobs[job_id] = {"status": "pending", "created": time.time()}

        def _runner():
            try:
                result = fn(*args, **kwargs)
                with self._lock:
                    job = self._jobs.get(job_id)
                    if job is not None:
                        job["status"] = "done"
                        job["result"] = result
            except Exception as e:  # keep the worker thread from dying silently
                with self._lock:
                    job = self._jobs.get(job_id)
                    if job is not None:
                        job["status"] = "error"
                        job["error"] = str(e)

        threading.Thread(target=_runner, daemon=True).start()
        return job_id

    def poll(self, job_id):
        """{"status": "pending"} | {"status": "done", "result": ...} |
        {"status": "error", "error": "..."} | {"status": "not_found"}"""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {"status": "not_found"}
        if job["status"] == "pending":
            return {"status": "pending"}
        if job["status"] == "error":
            return {"status": "error", "error": job.get("error", "Something went wrong.")}
        return {"status": "done", "result": job.get("result")}

    def get_result(self, job_id):
        """Result of a completed job, or None if it's missing/not done
        yet. Used by routes that re-render a full page from a finished
        job's result (see webapp/app.py's /screener/result/<id> and
        /backtest/result/<id>) rather than returning JSON to a poller."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job["status"] != "done":
            return None
        return job.get("result")
