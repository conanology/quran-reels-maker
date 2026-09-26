"""Small cross-process locks and durable file writes; no startup side effects."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time


class LockTimeoutError(TimeoutError):
    pass


_locks = {}
_locks_guard = threading.Lock()


@contextmanager
def exclusive_lock(path, timeout=30.0):
    """Hold an OS-owned lock. A terminated process releases it automatically."""
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("Lock timeout must be finite and nonnegative")
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locks_guard:
        local_lock = _locks.setdefault(str(path), threading.Lock())
    deadline = time.monotonic() + timeout
    if not local_lock.acquire(timeout=timeout):
        raise LockTimeoutError(f"Another job owns {path.name}")
    handle = None
    acquired = False
    try:
        handle = path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LockTimeoutError(f"Another job owns {path.name}")
                time.sleep(min(0.05, remaining))
        yield
    finally:
        if handle is not None:
            if acquired:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        local_lock.release()


def atomic_write_bytes(path, data, *, private=False):
    """Flush a sibling temporary file then replace, retaining the old file on error."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        if private:
            os.chmod(temporary, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if private:
            os.chmod(path, 0o600)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_write_json(path, data, *, private=False):
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    atomic_write_bytes(path, payload, private=private)
