"""`./run.sh --stop` / `--restart`: an instance started without a window
(file manager, launcher) can be ended from the command line."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import app.__main__ as entry
from app.__main__ import INSTANCE_INFO, _running_instance, stop_running_instance

BACKEND = Path(__file__).resolve().parents[1]

# Stands in for the running app: holds the data folder's lock and writes the
# instance file exactly as `python -m app` does, then idles.
HOLDER = """
import os, sys, time
from pathlib import Path
from app import instance_lock
from app.__main__ import _write_instance_info
data = Path(sys.argv[1])
lock = instance_lock.acquire(data)
_write_instance_info(data, "127.0.0.1", 8420)
print("ready", os.getpid(), flush=True)
time.sleep(60)
"""


def _start_holder(data_dir: Path) -> tuple[subprocess.Popen, int]:
    """The stand-in and its own pid — not always holder.pid: on Windows a
    venv's python.exe is a launcher that runs the interpreter as a child."""
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(data_dir)], cwd=BACKEND,
                              stdout=subprocess.PIPE, text=True)
    word, pid = holder.stdout.readline().split()
    assert word == "ready"
    return holder, int(pid)


def _end(holder: subprocess.Popen, pid: int) -> None:
    holder.kill()
    if pid != holder.pid:
        try:
            os.kill(pid, signal.SIGTERM)  # the interpreter behind the launcher
        except OSError:
            pass  # already ended


def test_stop_ends_a_running_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, "_looks_like_this_app", lambda pid, instance=None: True)  # the stand-in isn't `python -m app`
    holder, pid = _start_holder(tmp_path)
    try:
        instance = _running_instance(tmp_path)
        assert instance is not None and instance["pid"] == pid and instance["port"] == 8420
        assert stop_running_instance(tmp_path, timeout=10) == "stopped"
        holder.wait(timeout=10)
        assert _running_instance(tmp_path) is None
        time.sleep(0.2)  # atexit is skipped on SIGTERM; a stale info file must not matter
        assert stop_running_instance(tmp_path) == "not-running"
    finally:
        _end(holder, pid)


def test_stop_without_a_running_instance(tmp_path):
    (tmp_path / INSTANCE_INFO).write_text('{"pid": 999999, "port": 8420}', encoding="utf-8")  # stale
    assert stop_running_instance(tmp_path) == "not-running"


def test_a_process_that_is_not_the_app_is_never_stopped(tmp_path):
    """The info file names a pid; if that pid is some other program (the
    holder below is `python -c ...`), it is left alone."""
    holder, pid = _start_holder(tmp_path)
    try:
        if Path("/proc").exists():
            assert stop_running_instance(tmp_path, timeout=2) == "unknown"
            assert holder.poll() is None  # still running
    finally:
        _end(holder, pid)
