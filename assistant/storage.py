"""
Small shared JSON persistence helpers, used by watchlist.py,
watchlist_extras.py, and screener/config_store.py (saved screener setups).

Two reliability upgrades over a bare `json.dump(open(path, "w"))`:

  1. Atomic writes -- every save writes to a temp file in the same
     directory first, then os.replace()'s it over the real file.
     os.replace() is atomic on both POSIX and Windows, so a crash, power
     loss, or kill -9 mid-write can never leave a half-written, corrupt
     JSON file behind -- the real file is either the old version or the
     new one, never a truncated mix of both.

  2. Automatic backups + recovery -- every save also writes a timestamped
     snapshot into assistant_data/backups/ and rotates old ones (keeping
     the most recent MAX_BACKUPS_PER_FILE). If the main file is ever
     missing or unreadable, load_json() automatically falls back to the
     newest valid backup instead of silently returning {} and looking
     like the user's data vanished.

On top of that, this module registers a best-effort snapshot on process
exit (normal exit, Ctrl+C / SIGINT, or SIGTERM) covering every file saved
during the run -- so there's always a restore point tagged "shutdown"
sitting in assistant_data/backups/ from the last time the server (or CLI,
or bot) was running, independent of the individual per-edit backups above.
"""
import atexit
import json
import os
import signal
import sys
import tempfile
import threading
import time

from .config import DATA_DIR

BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

MAX_BACKUPS_PER_FILE = 8

_write_lock = threading.Lock()
_tracked_paths = set()  # every path saved via this module this run -- what gets backed up on shutdown


def load_json(path):
    """Load a JSON file, recovering from the newest backup if the primary
    file is missing, empty, or corrupt. Returns {} if nothing is recoverable."""
    data = _try_load(path)
    if data is not None:
        return data
    for backup_path in _backups_for(path):
        data = _try_load(backup_path)
        if data is not None:
            return data
    return {}


def save_json(path, data):
    """Atomically write `data` as JSON to `path`, then rotate a backup."""
    with _write_lock:
        _tracked_paths.add(path)
        _atomic_write(path, data)
        _write_backup(path, data)


def list_backups(path):
    """Newest-first list of {"file": path, "label": str, "mtime": float}
    for a given tracked JSON path -- used by the UI to show restore points."""
    out = []
    for bpath in _backups_for(path):
        try:
            out.append({"file": bpath, "label": os.path.basename(bpath),
                        "mtime": os.path.getmtime(bpath)})
        except OSError:
            continue
    return out


def restore_backup(path, backup_path):
    """Overwrite `path` with the contents of one of its own backups (as
    returned by list_backups). Refuses to touch files outside BACKUP_DIR."""
    backup_path = os.path.abspath(backup_path)
    if not backup_path.startswith(os.path.abspath(BACKUP_DIR) + os.sep):
        raise ValueError("Not a recognized backup file.")
    data = _try_load(backup_path)
    if data is None:
        raise ValueError("That backup file is missing or unreadable.")
    save_json(path, data)
    return data


def snapshot_all(tag="manual"):
    """Write one extra timestamped backup of every path saved during this
    process's lifetime. Called automatically on shutdown (tag='shutdown'),
    but also callable manually, e.g. before a risky bulk edit."""
    with _write_lock:
        for path in list(_tracked_paths):
            data = _try_load(path)
            if data is not None:
                _write_backup(path, data, tag=tag)


def _try_load(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _atomic_write(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _backup_name(path, tag=None):
    base = os.path.splitext(os.path.basename(path))[0]
    # Millisecond resolution (not just seconds) so two saves in quick
    # succession -- e.g. adding several tickers back-to-back -- get
    # distinct backup files instead of one silently overwriting the other.
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"{time.time() % 1:.3f}".lstrip("0")
    suffix = f"-{tag}" if tag else ""
    return os.path.join(BACKUP_DIR, f"{base}.{stamp}{suffix}.json")


def _backups_for(path):
    base = os.path.splitext(os.path.basename(path))[0]
    if not os.path.isdir(BACKUP_DIR):
        return []
    matches = [
        os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR)
        if f.startswith(base + ".") and f.endswith(".json")
    ]
    return sorted(matches, reverse=True)


def _write_backup(path, data, tag=None):
    try:
        with open(_backup_name(path, tag=tag), "w") as f:
            json.dump(data, f, indent=2)
        _rotate(path)
    except OSError:
        pass  # backups are best-effort -- never let one block the real (atomic) save


def _rotate(path):
    for old in _backups_for(path)[MAX_BACKUPS_PER_FILE:]:
        try:
            os.remove(old)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Best-effort snapshot on process exit -- covers normal exit, Ctrl+C, and a
# regular `kill` (SIGTERM). Doesn't try to survive kill -9 / power loss;
# that's what the atomic per-edit writes above are for.
# ---------------------------------------------------------------------------
def _on_exit(*_args):
    try:
        snapshot_all(tag="shutdown")
    except Exception:
        pass


atexit.register(_on_exit)

for _sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
    if _sig is None:
        continue
    try:
        _previous_handler = signal.getsignal(_sig)

        def _handler(signum, frame, _previous=_previous_handler):
            _on_exit()
            if callable(_previous) and _previous not in (signal.SIG_DFL, signal.SIG_IGN):
                _previous(signum, frame)
            else:
                sys.exit(0)

        signal.signal(_sig, _handler)
    except (ValueError, OSError, RuntimeError):
        # ValueError: not running in the main thread (e.g. imported from a
        # worker thread) -- atexit above still covers normal process exit.
        pass
