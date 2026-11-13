"""`./run.sh --stop` / `--restart`: an instance started without a window
(file manager, launcher) can be ended from the command line."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

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


@pytest.fixture(autouse=True)
def _never_ask_a_real_app(monkeypatch):
    """On Windows the app is asked to end itself before it is ended from
    outside. The stand-ins here answer no requests — and the port they name
    may be the one a real app listens on."""
    monkeypatch.setattr(entry, "_ASKED_TO_STOP", False)


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


def test_on_windows_the_app_is_asked_to_end_itself(tmp_path, monkeypatch):
    """os.kill() there cuts a process off in the middle of what it writes;
    asked, the app ends as on Ctrl+C."""
    running = [{"pid": 4711, "host": "127.0.0.1", "port": 8499}]
    asked, killed = [], []
    monkeypatch.setattr(entry, "_ASKED_TO_STOP", True)
    monkeypatch.setattr(entry, "_running_instance", lambda data_dir: running[0] if running else None)
    monkeypatch.setattr(entry, "_looks_like_this_app", lambda pid, instance=None: True)
    monkeypatch.setattr(entry, "_ask_to_stop", lambda instance: asked.append(instance["pid"]) or running.clear() or True)
    monkeypatch.setattr(entry.os, "kill", lambda pid, sig: killed.append(pid))

    assert stop_running_instance(tmp_path, timeout=2) == "stopped"
    assert asked == [4711] and killed == []


def test_an_app_that_does_not_answer_is_ended_from_outside(tmp_path, monkeypatch):
    """An older version without that request, or one that hangs."""
    running = [{"pid": 4711, "host": "127.0.0.1", "port": 8499}]
    killed = []
    monkeypatch.setattr(entry, "_ASKED_TO_STOP", True)
    monkeypatch.setattr(entry, "_running_instance", lambda data_dir: running[0] if running else None)
    monkeypatch.setattr(entry, "_looks_like_this_app", lambda pid, instance=None: True)
    monkeypatch.setattr(entry, "_ask_to_stop", lambda instance: False)
    monkeypatch.setattr(entry.os, "kill", lambda pid, sig: killed.append(pid) or running.clear())

    assert stop_running_instance(tmp_path, timeout=2) == "stopped"
    assert killed == [4711]


def test_the_app_ends_itself_only_when_it_is_the_one_meant(client, monkeypatch):
    from app.api.routes import system

    ended = []
    monkeypatch.setattr(system, "_end_as_ctrl_c", lambda: ended.append(True))

    # another copy of the app listens on the port the stopped one had
    assert client.post("/api/system/stop", json={"pid": os.getpid() + 1}).status_code == 409
    time.sleep(0.4)
    assert ended == []

    assert client.post("/api/system/stop", json={"pid": os.getpid()}).status_code == 202
    deadline = time.monotonic() + 3
    while not ended and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ended == [True]
