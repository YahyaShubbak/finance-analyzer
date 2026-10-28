"""One process at a time per data folder: the app while it runs, or the
installer's data move (app.legacy_migration).

The app holds an OS file lock on ``<data dir>/.app-running.lock`` for as long
as it runs. The lock is released by the operating system when the process
ends, however it ends (Ctrl+C, closed window, crash), so a stale lock file
left on disk never blocks anything — only a live holder does.

Why not just the port or the database: the installer checked whether the
configured port answered, which misses an app started with ``--port``; and
an open SQLite connection only exists after the first request that touches
the database. A running app that has not touched it yet still has the old
data folder in memory and would create a new, empty database there on its
next request if the data were moved away under it.

Stdlib only, so the installer can use it before the app's settings are valid.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO

LOCK_FILENAME = ".app-running.lock"


class AlreadyLockedError(RuntimeError):
    """Another live process holds the lock for this data folder."""


class LockUnavailableError(RuntimeError):
    """The lock could not be taken for another reason: a file system without
    locks (some network shares), or a folder we may not write to. Callers
    carry on without it rather than claim the app is running."""


# What a lock held by someone else looks like: EACCES/EDEADLOCK from
# msvcrt.locking, EWOULDBLOCK/EAGAIN from flock.
_HELD_ELSEWHERE = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}


def acquire(data_dir: Path) -> BinaryIO:
    """Take the lock for `data_dir` without waiting. Keep the returned file
    open for as long as the lock must be held; closing it releases the lock."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        handle = open(data_dir / LOCK_FILENAME, "a+b")  # held open on purpose: the lock lives with it
    except OSError as exc:
        raise LockUnavailableError(f"{data_dir}: {exc}") from exc
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            # Locks one byte (beyond the end of the empty file is allowed);
            # LK_NBLCK fails at once instead of retrying for 10 s.
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in _HELD_ELSEWHERE:
            raise AlreadyLockedError(str(data_dir)) from exc
        raise LockUnavailableError(f"{data_dir}: {exc}") from exc
    return handle


def release(handle: BinaryIO) -> None:
    handle.close()  # the OS drops the lock with the last handle
