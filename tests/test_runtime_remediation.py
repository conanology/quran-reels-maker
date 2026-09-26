import json
from pathlib import Path
import threading
import pytest
from core.runtime_safety import atomic_write_json, exclusive_lock, LockTimeoutError


def test_atomic_failure_preserves_previous_file(tmp_path, monkeypatch):
    import core.runtime_safety as safety
    target = tmp_path / "state.json"
    atomic_write_json(target, {"version": 1})
    def fail_replace(*args):
        raise OSError("simulated interruption")
    monkeypatch.setattr(safety.os, "replace", fail_replace)
    with pytest.raises(OSError):
        atomic_write_json(target, {"version": 2})
    assert json.loads(target.read_text()) == {"version": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_lock_excludes_thread_then_releases(tmp_path):
    target = tmp_path / "job.lock"
    outcomes = []
    def contender():
        try:
            with exclusive_lock(target, timeout=0.05):
                outcomes.append("entered")
        except LockTimeoutError:
            outcomes.append("blocked")
    with exclusive_lock(target):
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(timeout=1)
        assert outcomes == ["blocked"]
    contender()
    assert outcomes == ["blocked", "entered"]


def test_nonfinite_json_does_not_replace(tmp_path):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"value": 1})
    with pytest.raises(ValueError):
        atomic_write_json(target, {"value": float("nan")})
    assert json.loads(target.read_text()) == {"value": 1}


def test_kernel_lock_excludes_another_process_and_releases(tmp_path):
    import subprocess
    import sys
    script = """import sys
from core.runtime_safety import exclusive_lock, LockTimeoutError
try:
    with exclusive_lock(sys.argv[1], timeout=0.1):
        print('entered')
except LockTimeoutError:
    print('blocked')
"""
    target = tmp_path / "process.lock"
    def contender():
        return subprocess.run([sys.executable, "-c", script, str(target)],
                              capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    with exclusive_lock(target):
        assert contender() == "blocked"
    assert contender() == "entered"
