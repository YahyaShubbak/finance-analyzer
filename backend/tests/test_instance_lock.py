"""app.instance_lock: one live process per data folder (the app, or the
installer's data move)."""
from __future__ import annotations

import errno
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import instance_lock

BACKEND_DIR = Path(__file__).resolve().parents[1]

_HOLDER = """
import sys, time
from pathlib import Path
from app import instance_lock
handle = instance_lock.acquire(Path(sys.argv[1]))
print("locked", flush=True)
time.sleep(60)
"""


def hold_lock_in_another_process(data_dir: Path) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-c", _HOLDER, str(data_dir)], cwd=BACKEND_DIR,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "locked"
    return proc


def test_a_second_holder_is_refused_until_the_first_releases(tmp_path):
    first = instance_lock.acquire(tmp_path)
    with pytest.raises(instance_lock.AlreadyLockedError):
        instance_lock.acquire(tmp_path)
    instance_lock.release(first)
    instance_lock.release(instance_lock.acquire(tmp_path))


def test_a_lock_held_by_another_process_is_seen(tmp_path):
    proc = hold_lock_in_another_process(tmp_path)
    try:
        with pytest.raises(instance_lock.AlreadyLockedError):
            instance_lock.acquire(tmp_path)
    finally:
        proc.kill()
        proc.wait()


def test_a_lock_file_left_by_a_killed_process_does_not_block(tmp_path):
    proc = hold_lock_in_another_process(tmp_path)
    proc.kill()  # like a crash or a closed console window: no clean-up runs
    proc.wait()
    assert (tmp_path / instance_lock.LOCK_FILENAME).exists()

    for _ in range(50):  # the OS may need a moment to drop the dead process's lock
        try:
            instance_lock.release(instance_lock.acquire(tmp_path))
            break
        except instance_lock.AlreadyLockedError:
            time.sleep(0.1)
    else:
        pytest.fail("the lock of a killed process was never released")


def test_a_file_system_without_locks_is_not_mistaken_for_a_running_app(tmp_path, monkeypatch):
    def no_locks(*_args):
        raise OSError(errno.ENOLCK, "No locks available")  # e.g. NFS without lockd

    if sys.platform == "win32":
        import msvcrt
        monkeypatch.setattr(msvcrt, "locking", no_locks)
    else:
        import fcntl
        monkeypatch.setattr(fcntl, "flock", no_locks)

    with pytest.raises(instance_lock.LockUnavailableError):
        instance_lock.acquire(tmp_path)


@pytest.fixture()
def entry(tmp_path, monkeypatch):
    """app.__main__ with its side effects contained and uvicorn stubbed."""
    import uvicorn

    import app.__main__ as entry_module
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    # main() writes the effective host/port into os.environ and settings;
    # registering them here makes monkeypatch restore them afterwards.
    for name in ("host", "port", "using_legacy_layout"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setenv("FINANCE_HOST", settings.host)
    monkeypatch.setenv("FINANCE_PORT", str(settings.port))
    started = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(True))
    monkeypatch.setattr(entry_module, "_instance_lock", None)
    yield entry_module, started
    if entry_module._instance_lock is not None:
        instance_lock.release(entry_module._instance_lock)


def test_the_app_refuses_to_start_twice_on_the_same_data(entry, tmp_path, capsys):
    module, started = entry
    proc = hold_lock_in_another_process(tmp_path)  # the instance that is already running
    try:
        assert module.main(["--port", "8499", "--no-open"]) == 1
    finally:
        proc.kill()
        proc.wait()
    assert not started
    assert "already running" in capsys.readouterr().err


def test_the_app_still_starts_where_locking_is_unsupported(entry, monkeypatch, capsys):
    module, started = entry

    def unavailable(_data_dir):
        raise instance_lock.LockUnavailableError("no locks here")

    monkeypatch.setattr(instance_lock, "acquire", unavailable)
    assert module.main(["--port", "8499", "--no-open"]) == 0
    assert started
    assert "could not lock" in capsys.readouterr().err


def test_a_normal_legacy_layout_start_is_not_blocked(entry, monkeypatch):
    """The "just moved" check must only fire when the old database is gone."""
    module, started = entry
    from app.config import settings

    monkeypatch.setattr(settings, "using_legacy_layout", True)
    monkeypatch.setattr(module, "legacy_database_exists", lambda: True)
    assert module.main(["--port", "8499", "--no-open"]) == 0
    assert started


def test_the_app_does_not_start_on_a_just_emptied_legacy_folder(entry, monkeypatch, capsys):
    """Found in review: settings are read before the lock is taken; if the
    move finished in between, the old folder is empty and the app would
    create a new, empty database there."""
    module, started = entry
    from app.config import settings

    monkeypatch.setattr(settings, "using_legacy_layout", True)
    monkeypatch.setattr(module, "legacy_database_exists", lambda: False)
    assert module.main(["--port", "8499", "--no-open"]) == 1
    assert not started
    assert "just moved" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --open
# ---------------------------------------------------------------------------

def test_the_browser_is_opened_only_once_the_app_answers(monkeypatch):
    """The port listens after start-up finished (a database upgrade can take
    a while); opened on a timer, the browser showed "connection refused"."""
    import webbrowser

    import app.__main__ as module

    answers = iter([False, False, True])
    probed, opened = [], []
    monkeypatch.setattr(module, "_answers_as_this_app", lambda url: probed.append(url) or next(answers))
    monkeypatch.setattr(webbrowser, "open", opened.append)

    assert module._open_browser_when_ready("http://127.0.0.1:8499", timeout=5, poll=0) is True
    assert len(probed) == 3 and opened == ["http://127.0.0.1:8499"]


def test_the_browser_is_not_opened_for_an_app_that_never_comes_up(monkeypatch):
    import webbrowser

    import app.__main__ as module

    opened = []
    monkeypatch.setattr(module, "_answers_as_this_app", lambda _url: False)
    monkeypatch.setattr(webbrowser, "open", opened.append)

    assert module._open_browser_when_ready("http://127.0.0.1:8499", timeout=0.05, poll=0.01) is False
    assert opened == []


def test_open_waits_for_the_app_instead_of_a_fixed_delay(entry, monkeypatch):
    import threading

    module, started = entry
    asked, waiting = [], threading.Event()
    monkeypatch.setattr(module, "_open_browser_when_ready", lambda url: (asked.append(url), waiting.set()))

    assert module.main(["--port", "8499", "--open"]) == 0
    assert started
    assert waiting.wait(5) and asked == ["http://127.0.0.1:8499"]


def test_starting_the_running_app_again_with_open_just_opens_the_browser(entry, monkeypatch, capsys):
    """The Start-menu shortcut clicked a second time: the app is there, so
    show it — not an error message in a window that waits for a key."""
    import webbrowser

    module, started = entry
    opened = []
    monkeypatch.setattr(module, "_port_available", lambda _host, _port: False)
    monkeypatch.setattr(module, "_answers_as_this_app", lambda _url: True)
    monkeypatch.setattr(module, "_running_instance", lambda _data_dir: {"pid": 1, "host": "127.0.0.1", "port": 8499})
    monkeypatch.setattr(webbrowser, "open", opened.append)

    assert module.main(["--port", "8499", "--open"]) == 0
    assert opened == ["http://127.0.0.1:8499"] and not started

    # without --open it stays what it was: a hint, and no second instance
    assert module.main(["--port", "8499", "--no-open"]) == 1
    assert opened == ["http://127.0.0.1:8499"] and not started
    assert "already running" in capsys.readouterr().err


def test_status_tells_a_running_app_from_none(entry, tmp_path, capsys):
    """For the installers: an app that runs is stopped before its packages are replaced."""
    module, started = entry
    assert module.main(["--status"]) == module.EXIT_NOT_RUNNING == 3
    assert "not running" in capsys.readouterr().out

    proc = hold_lock_in_another_process(tmp_path)  # the app, running
    try:
        assert module.main(["--status"]) == 0
        assert "is running" in capsys.readouterr().out
    finally:
        proc.kill()
        proc.wait()
    assert not started  # asking never starts it
