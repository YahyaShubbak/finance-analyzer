"""`python -m app` — start the Local Finance Analyzer.

Used by run.sh / run.bat. Host, port and "open browser" come from
finance.env / FINANCE_* environment variables (see app.config) and can be
overridden on the command line.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from app import instance_lock
from app.config import legacy_database_exists, settings

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_instance_lock = None  # the open lock file while the app runs
# Next to the lock: which process holds it, so `--stop` can end an instance
# that runs without a window (started from the file manager or a launcher).
INSTANCE_INFO = ".app-running.json"


def _write_instance_info(data_dir: Path, host: str, port: int) -> None:
    path = data_dir / INSTANCE_INFO
    try:
        path.write_text(json.dumps({"pid": os.getpid(), "host": host, "port": port}), encoding="utf-8")
    except OSError:
        return  # only a convenience for --stop
    atexit.register(lambda: path.unlink(missing_ok=True))


def _running_instance(data_dir: Path) -> dict | None:
    """The live instance using `data_dir`, if any: {"pid", "host", "port"}
    (pid None if it can't be told, e.g. the installer holds the lock)."""
    try:
        probe = instance_lock.acquire(data_dir)
    except instance_lock.AlreadyLockedError:
        pass
    except instance_lock.LockUnavailableError:
        return None
    else:
        instance_lock.release(probe)
        return None
    try:
        info = json.loads((data_dir / INSTANCE_INFO).read_text(encoding="utf-8"))
        return {"pid": int(info["pid"]), "host": info.get("host"), "port": info.get("port")}
    except (OSError, ValueError, KeyError, TypeError):
        return {"pid": None, "host": None, "port": None}


def _looks_like_this_app(pid: int, instance: dict | None = None) -> bool:
    cmdline = Path(f"/proc/{pid}/cmdline")
    if not cmdline.exists():
        # no /proc (macOS, Windows): the pid could be a reused one (e.g. while the
        # installer holds the lock), so the app must answer on its recorded port
        if not instance or not instance.get("port"):
            return False
        host = instance.get("host") or "127.0.0.1"
        host = "127.0.0.1" if host in ("0.0.0.0", "::") else host  # noqa: S104 — detects, not binds
        return _answers_as_this_app(f"http://{f'[{host}]' if ':' in host else host}:{instance['port']}")
    parts = cmdline.read_bytes().split(b"\0")
    if not (b"app" in parts and b"-m" in parts):
        return False
    # any "python -m app" could have taken a reused pid: this app runs from its own backend folder
    try:
        return Path(f"/proc/{pid}/cwd").resolve() == Path(__file__).resolve().parents[1]
    except OSError:  # not ours to look at: ask the instance itself
        return bool(instance and instance.get("port")) and _answers_as_this_app(
            f"http://127.0.0.1:{instance['port']}")


def stop_running_instance(data_dir: Path, timeout: float = 15.0) -> str:
    """Ends the instance that uses `data_dir`. Returns "stopped",
    "not-running" or "unknown" (running, but not ours to stop)."""
    instance = _running_instance(data_dir)
    if instance is None:
        return "not-running"
    pid = instance["pid"]
    if pid is None or pid == os.getpid() or not _looks_like_this_app(pid, instance):
        return "unknown"
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "not-running"
    except OSError:
        return "unknown"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _running_instance(data_dir) is None:
            return "stopped"
        time.sleep(0.2)
    return "unknown"


def _answers_as_this_app(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=2) as response:  # noqa: S310 — always http://
            return json.loads(response.read()).get("status") == "ok"
    except (OSError, ValueError):
        return False


#: how long `--open` waits for the app to answer before giving up on opening the browser
OPEN_BROWSER_TIMEOUT_SECONDS = 300.0


def _open_browser_when_ready(url: str, timeout: float = OPEN_BROWSER_TIMEOUT_SECONDS, poll: float = 0.3) -> bool:
    """Open the browser once the app answers. The port only listens after
    start-up finished — upgrading the database, reading stored statements
    again after an update — which can take much longer than a moment: opened
    earlier, the browser shows "connection refused". Returns whether it
    was opened."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _answers_as_this_app(url):
            webbrowser.open(url)
            return True
        time.sleep(poll)
    return False


def _port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if os.name != "nt":
            # Like uvicorn itself: connections of a just-stopped instance
            # linger in TIME_WAIT and must not count as "in use" (a real
            # listener still makes bind fail). On Windows SO_REUSEADDR would
            # allow binding over an active listener, so it's POSIX only.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app", description="Start the Local Finance Analyzer.")
    parser.add_argument("--host", default=settings.host, help=f"interface to bind (default: {settings.host})")
    parser.add_argument("--port", type=int, default=None, help=f"port (default: {settings.port})")
    parser.add_argument("--open", action=argparse.BooleanOptionalAction, default=settings.open_browser,
                        help="open the app in the default browser once it is running")
    parser.add_argument("--reload", action="store_true", help="development: restart on code changes")
    parser.add_argument("--stop", action="store_true",
                        help="stop the running app (also one started without a window) and exit")
    parser.add_argument("--restart", action="store_true", help="stop the running app, then start it again")
    args = parser.parse_args(argv)
    os.umask(0o077)  # bank data: readable by this user only (as run.sh does), also when started directly

    previous = _running_instance(settings.data_dir) if args.restart else None
    if args.port is None:
        # --restart comes back on the port the stopped instance used
        args.port = int(previous["port"]) if previous and previous.get("port") else settings.port

    if args.stop or args.restart:
        outcome = stop_running_instance(settings.data_dir)
        if outcome == "stopped":
            print("The running app was stopped.")
        elif outcome == "not-running":
            print("The app was not running.")
        else:
            print("ERROR: the app seems to be running, but could not be stopped from here.", file=sys.stderr)
            print("  Close the window it runs in, or end the Python process (task manager).", file=sys.stderr)
            return 1
        if args.stop:
            return 0

    # Make the effective values visible to the app (and to the reloader's
    # child process), e.g. for the Host-header check.
    os.environ["FINANCE_HOST"] = args.host
    os.environ["FINANCE_PORT"] = str(args.port)
    settings.host, settings.port = args.host, args.port

    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host  # noqa: S104 — detects, not binds
    url = f"http://{f'[{shown_host}]' if ':' in shown_host else shown_host}:{args.port}"

    if not _port_available(args.host, args.port):
        if _answers_as_this_app(url) and _running_instance(settings.data_dir) is None:
            # another copy of the app, with other data: --stop/--restart here wouldn't reach it
            print(f"ERROR: port {args.port} is used by another copy of this app (with a different data folder).",
                  file=sys.stderr)
            print(f"  Start this one on another port:  ./run.sh --port {args.port + 1}"
                  f"   (Windows: run.bat --port {args.port + 1})", file=sys.stderr)
        elif _answers_as_this_app(url) and args.open:
            # Started again to get to the app (the Start-menu shortcut, a
            # second double-click): that is what happens — not an error.
            print(f"The app is already running: opening {url}")
            webbrowser.open(url)
            return 0
        elif _answers_as_this_app(url):
            print(f"The app is already running: open {url}", file=sys.stderr)
            print("  (It may have been started without a window, e.g. from the file manager.)", file=sys.stderr)
            print("  To start it anew:   ./run.sh --restart   (Windows: run.bat --restart)", file=sys.stderr)
            print("  To stop it:         ./run.sh --stop      (Windows: run.bat --stop)", file=sys.stderr)
        else:
            print(f"ERROR: port {args.port} is used by another program.", file=sys.stderr)
            print(f"  Start the app on another port:  ./run.sh --port {args.port + 1}"
                  f"   (Windows: run.bat --port {args.port + 1})", file=sys.stderr)
        return 1

    # Held until the process exits (see app.instance_lock): keeps a second
    # instance, and the installer's data move, away from this data folder.
    global _instance_lock
    try:
        _instance_lock = instance_lock.acquire(settings.data_dir)
    except instance_lock.AlreadyLockedError:
        print(f"ERROR: the app is already running with the data in {settings.data_dir}", file=sys.stderr)
        print("  (or the installer is moving that data right now).", file=sys.stderr)
        print("  Stop it with ./run.sh --stop (Windows: run.bat --stop), or start anew with --restart.",
              file=sys.stderr)
        return 1
    except instance_lock.LockUnavailableError as exc:
        print(f"WARNING: could not lock the data folder ({exc}); a second instance would not be detected.",
              file=sys.stderr)
    # The settings were read before the lock was taken. If the installer moved
    # the old in-repo data in between, that folder is now empty: starting on
    # it would create a new, empty database and hide the moved one.
    if settings.using_legacy_layout and not legacy_database_exists():
        print("ERROR: your data was just moved to its new folder. Start the app again.", file=sys.stderr)
        return 1

    if _instance_lock is not None:
        _write_instance_info(settings.data_dir, args.host, args.port)

    print("Local Finance Analyzer")
    print(f"  Open:       {url}")
    print(f"  Data:       {settings.data_dir}")
    print("  Stop:       press Ctrl+C in this window, or run ./run.sh --stop")
    if args.host not in _LOCAL_HOSTS:
        print(f"  WARNING: listening on {args.host} — the app has no login; anyone who can reach this "
              f"address can see your data.", file=sys.stderr)
    print(flush=True)

    if args.open:
        # (a daemon thread: it must not keep a failed start-up from ending)
        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
