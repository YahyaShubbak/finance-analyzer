"""Move a pre-0.2 data layout out of the program folder — verified, resumable.

``python -m app.legacy_migration --repo-root R --target T`` is run by
install.sh / install.ps1 when the user agrees to move their old in-repo data
(``R/data/finance.db`` plus ``R/imports``, ``R/exports``, ``R/backups`` and
``R/data/.staging``) to the data folder ``T``.

This replaces a plain file-by-file move, which could fail half-way (a locked
file, a full disk) with the database already in ``T`` but ``finance.env`` not
yet pointing there — the app would then open an empty database elsewhere. The
order here guarantees that at every moment exactly one complete copy is the
one the app will use:

1. **The app must not be running.** The running app holds the
   ``app.instance_lock`` of its data folder, whichever port it uses and
   whether or not it has opened the database yet; the move takes the same
   lock for the old and the new folder and keeps it to the end, so the app
   cannot start half-way through either. Other programs (an SQLite browser)
   are caught by switching the database out of WAL mode, as long as it is
   in WAL mode (the app always leaves it so; a run aborted after this step
   leaves DELETE mode until the app opens it again): the switch needs every
   other connection closed, so ``PRAGMA journal_mode=DELETE`` fails with
   "database is locked" while anything has it open. The switch also folds
   any WAL content into the main file, so nothing still pending in ``-wal``
   is left behind. (The app turns WAL back on at its next connection.)
2. **Copy, never move.** The database goes through SQLite's backup API into
   ``finance.db.partial``, which must pass ``integrity_check`` and match the
   source's row count in every table before it is renamed to ``finance.db``.
   Every other file is copied to ``<name>.partial``, its SHA-256 compared,
   then renamed. A file that already exists in ``T`` is skipped and the
   original kept (reported, never overwritten).
3. **No writes in between.** Before ``finance.env`` changes, the source is
   locked with ``BEGIN EXCLUSIVE`` and ``PRAGMA data_version`` must be what
   it was before the copy, i.e. nobody wrote to it since.
4. **Switch.** ``FINANCE_DATA_DIR`` in ``finance.env`` is replaced atomically
   (temp file + ``os.replace``). From here on the app uses ``T``.
5. **Clean up.** Only now are the originals that were copied deleted, then
   the empty old folders.

A marker file ``T/.legacy-migration`` exists from step 2 until the switch in
step 4. If an earlier run stopped before the switch, the marker tells the
next run that a ``finance.db`` in ``T`` is its own unfinished copy, which may
be replaced — without the marker an existing ``T/finance.db`` is someone
else's database (or, after the switch, the live one) and the migration
refuses to touch it.

``T`` must lie outside the program folder: otherwise source and target
overlap and "copied" files would be deleted as duplicates of themselves.
Copied files are fsynced before the switch, so a power cut right after the
run cannot leave empty copies behind deleted originals.

Deliberately stdlib-only and independent of ``app.config``: it must work
before the app's settings are valid for the new layout, and a mistake in
``finance.env`` must not stop it from running.

Exit status: 0 done (or nothing to do), 1 failed (the old data is untouched
and still in use), 2 the app is running, 3 ``T`` already holds a database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app import instance_lock

DATABASE_FILENAME = "finance.db"
MARKER_NAME = ".legacy-migration"
CONFIG_KEY = "FINANCE_DATA_DIR"

# (folder in the old layout, relative to the repo root) -> (folder in the data dir)
LEGACY_FOLDERS: tuple[tuple[str, str], ...] = (
    ("imports", "imports"),
    ("exports", "exports"),
    ("backups", "backups"),
    ("data/.staging", ".staging"),
)
# Placeholders that keep empty folders in git; they are not user data.
IGNORED_NAMES = {".gitkeep"}

EXIT_FAILED = 1
EXIT_IN_USE = 2
EXIT_TARGET_HAS_DATABASE = 3


class MigrationError(Exception):
    exit_code = EXIT_FAILED


class DatabaseInUseError(MigrationError):
    exit_code = EXIT_IN_USE


class TargetHasDatabaseError(MigrationError):
    exit_code = EXIT_TARGET_HAS_DATABASE


@dataclass
class MigrationResult:
    target: Path
    switched: bool = False  # finance.env points to `target`; from here on the move counts as done
    copied_files: int = 0
    kept_files: list[Path] = field(default_factory=list)      # originals kept because the target existed
    leftover_files: list[Path] = field(default_factory=list)  # copied, but the original could not be deleted


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row count of every table — all of them, not just the app's known ones,
    so a table added by a later schema version is verified too."""
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def _open_exclusively(db_path: Path) -> sqlite3.Connection:
    """Open the old database, proving nothing else has it open (step 1)."""
    conn = sqlite3.connect(str(db_path), timeout=1.0, isolation_level=None)
    try:
        mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
    except sqlite3.OperationalError as exc:
        conn.close()
        if "locked" in str(exc) or "busy" in str(exc):
            raise DatabaseInUseError(
                f"The database {db_path} is in use. Stop the app (close its window or press Ctrl+C) "
                "and any program that has the file open, then run the installer again.") from exc
        raise MigrationError(f"Cannot open the database {db_path}: {exc}") from exc
    if mode != "delete":
        conn.close()
        raise DatabaseInUseError(
            f"The database {db_path} could not be prepared for the move (journal mode stayed {mode!r}). "
            "Stop the app and run the installer again.")
    return conn


def _copy_database(source: sqlite3.Connection, source_path: Path, target_db: Path) -> None:
    """Backup-API copy into ``.partial``, verified, then renamed (step 2)."""
    partial = target_db.with_name(target_db.name + ".partial")
    partial.unlink(missing_ok=True)
    expected = _row_counts(source)
    dest = sqlite3.connect(str(partial))
    try:
        # No transaction may be open on `source` here: the backup API waits
        # for the source's lock, so it would block on our own EXCLUSIVE.
        source.backup(dest)
        integrity = dest.execute("PRAGMA integrity_check").fetchone()[0]
        actual = _row_counts(dest)
    finally:
        dest.close()
    if integrity != "ok":
        partial.unlink(missing_ok=True)
        raise MigrationError(f"The copy of {source_path} failed SQLite's integrity check: {integrity}")
    if actual != expected:
        partial.unlink(missing_ok=True)
        raise MigrationError(f"The copy of {source_path} does not match the original (rows {actual} vs {expected}).")
    os.replace(partial, target_db)


def _fsync_file(path: Path) -> None:
    """Force the file's content to disk. Without it a power cut shortly after
    the run can leave a zero-length copy on disk while the deletion of the
    original already made it (delayed allocation on ext4, lazy writes on
    NTFS). r+b: Windows only syncs handles opened for writing."""
    with path.open("r+b") as fh:
        os.fsync(fh.fileno())


def _fsync_dir(path: Path) -> None:
    """Make renames inside `path` durable (POSIX; Windows has no directory
    handles to sync, and NTFS journals renames itself)."""
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_file(src: Path, dst: Path) -> None:
    partial = dst.with_name(dst.name + ".partial")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, partial)
    _fsync_file(partial)
    if _sha256(partial) != _sha256(src):
        partial.unlink(missing_ok=True)
        raise MigrationError(f"The copy of {src} does not match the original.")
    os.replace(partial, dst)
    _fsync_dir(dst.parent)


def _legacy_files(repo_root: Path, target: Path) -> list[tuple[Path, Path]]:
    pairs = []
    for old, new in LEGACY_FOLDERS:
        src_dir = repo_root / old
        if not src_dir.is_dir():
            continue
        for src in sorted(p for p in src_dir.rglob("*") if p.is_file()):
            if src.name in IGNORED_NAMES or src.name.endswith(".partial"):
                continue
            pairs.append((src, target / new / src.relative_to(src_dir)))
    return pairs


def env_quote(value: str) -> str:
    """Quote a value the way install.sh / install.ps1 do, so either can read
    it back as the next run's default. Windows paths get forward slashes:
    python-dotenv would turn the "\\\\" of a UNC path into "\\"."""
    if os.name == "nt":
        value = value.replace("\\", "/")
    return "'" + value.replace("'", "\\'") + "'"


def set_config_value(config_file: Path, key: str, value: str) -> None:
    """Replace (or add) one KEY=value line, keeping every other line, written
    atomically so a crash leaves either the old or the new file (step 4)."""
    lines = config_file.read_text(encoding="utf-8-sig").splitlines() if config_file.exists() else []
    new_line = f"{key}={env_quote(value)}"
    lines = [line for line in lines if not line.startswith(f"{key}=")]
    lines.append(new_line)
    tmp = config_file.with_name(config_file.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, config_file)
    # The directory fsync (making the rename itself durable) is the caller's
    # job and must not fail the switch: once os.replace returned, the new
    # file is what the app reads.


def config_points_to(config_file: Path, target: Path) -> bool:
    """Does finance.env already name `target` as the data folder? Read back
    from disk, so the answer is right even when the run was interrupted
    between os.replace and recording that the switch happened."""
    try:
        lines = config_file.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return False
    return f"{CONFIG_KEY}={env_quote(str(target))}" in lines


def _remove_empty_dirs(repo_root: Path) -> None:
    """Remove the old folders' now-empty subfolders, then the empty old
    folders themselves. rmdir refuses anything that still has content, so a
    kept file (or a .gitkeep) keeps its folder."""
    subdirs = [d for old, _ in LEGACY_FOLDERS if (repo_root / old).is_dir()
               for d in (repo_root / old).rglob("*") if d.is_dir()]
    tops = [repo_root / rel for rel in ("data/.staging", "data/imports", "data/exports", "data/backups", "data", "backups")]
    for d in sorted(subdirs, key=lambda p: len(p.parts), reverse=True) + tops:  # deepest first
        try:
            d.rmdir()
        except OSError:
            pass  # missing or not empty: either way nothing to do


def migrate(repo_root: Path, target: Path, config_file: Path,
            result: MigrationResult | None = None) -> MigrationResult:
    """`result` may be passed in so the caller can still read `switched`
    when an exception (even Ctrl+C) ends the run after the switch."""
    repo_root, target = repo_root.resolve(), target.resolve()
    source_db = repo_root / "data" / DATABASE_FILENAME
    target_db = target / DATABASE_FILENAME
    marker = target / MARKER_NAME
    if result is None:
        result = MigrationResult(target=target)
    result.target = target

    if not source_db.exists():
        return result  # nothing (left) to move
    # Inside the program folder, source and target overlap: the repo root's
    # imports/ would be its own "copy" and deleted as a duplicate, and a
    # target inside backups/ would have its fresh database copy treated as
    # an old file. The whole point of the move is to leave that folder anyway.
    if target == repo_root or target.is_relative_to(repo_root):
        raise MigrationError(f"The data folder {target} is inside the program folder {repo_root}. "
                             "Choose a folder outside it (the default is fine).")

    try:
        resuming = marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("source") == str(repo_root)
    except (ValueError, AttributeError):
        resuming = False  # unreadable marker: treat an existing database as foreign
    if target_db.exists() and not resuming:
        raise TargetHasDatabaseError(
            f"{target} already contains a database — not overwriting it. "
            f"Move {repo_root / 'data'} by hand or choose another data folder.")

    # Step 1, part one: the app holds this lock while it runs, whether or not
    # it has the database open yet. Held until the end, it also keeps the app
    # from starting half-way through the move.
    locks = []
    try:
        for data_dir in (repo_root / "data", target):
            try:
                locks.append(instance_lock.acquire(data_dir))
            except instance_lock.LockUnavailableError:
                # File system without locks (some network shares): the
                # journal-mode check and the installer's port check remain.
                pass
    except instance_lock.AlreadyLockedError as exc:
        for handle in locks:
            instance_lock.release(handle)
        raise DatabaseInUseError(
            f"The app is running (with the data in {exc}). Stop it (close its window or press Ctrl+C), "
            "then run the installer again.") from exc
    try:
        return _migrate_locked(repo_root, target, config_file, source_db, target_db, marker, result)
    finally:
        for handle in locks:
            instance_lock.release(handle)
        # The old folder's lock file is ours now; without it data/ can go.
        try:
            (repo_root / "data" / instance_lock.LOCK_FILENAME).unlink(missing_ok=True)
            _remove_empty_dirs(repo_root)
        except OSError:
            pass  # cosmetic only


def _migrate_locked(repo_root: Path, target: Path, config_file: Path, source_db: Path, target_db: Path,
                    marker: Path, result: MigrationResult) -> MigrationResult:
    source = _open_exclusively(source_db)
    try:
        target.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"source": str(repo_root)}), encoding="utf-8")

        version_before = source.execute("PRAGMA data_version").fetchone()[0]
        _copy_database(source, source_db, target_db)

        copied: list[Path] = []
        for src, dst in _legacy_files(repo_root, target):
            if dst.exists():
                if _sha256(dst) == _sha256(src):
                    copied.append(src)  # identical copy from an earlier, interrupted run
                else:
                    result.kept_files.append(src)
                continue
            _copy_file(src, dst)
            copied.append(src)
        result.copied_files = len(copied)

        # Step 3: lock out every other connection and make sure nobody wrote
        # to the old database while it was being copied.
        try:
            source.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise DatabaseInUseError("The app (or another program) opened the database while it was being "
                                     "copied. Stop it and run the installer again.") from exc
        if source.execute("PRAGMA data_version").fetchone()[0] != version_before:
            raise DatabaseInUseError("The database was changed while it was being copied. "
                                     "Stop the app and run the installer again.")
        _fsync_dir(target)
        set_config_value(config_file, CONFIG_KEY, str(target))
        result.switched = True
        # Right away, not at the end: a marker that outlived the switch would
        # let a later run take the live database in `target` for its own
        # unfinished copy and replace it.
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            result.leftover_files.append(marker)
        try:
            _fsync_dir(config_file.parent)
        except OSError:
            pass  # durability of the rename only; the switch already happened
    finally:
        source.close()  # also ends the EXCLUSIVE transaction (rolled back, nothing was written)

    # Step 5: the app now uses `target`. Failures here only leave redundant
    # old copies behind, which are reported.
    for path in [source_db, Path(f"{source_db}-wal"), Path(f"{source_db}-shm"), *copied]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            result.leftover_files.append(path)
    _remove_empty_dirs(repo_root)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="finance.env to update (default: <repo-root>/finance.env)")
    args = parser.parse_args(argv)
    config_file = args.config or args.repo_root / "finance.env"
    # A redirected stdout on Windows is cp1252; a path it cannot encode must
    # not turn a finished move into a reported failure.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="backslashreplace")

    result = MigrationResult(target=args.target)
    # Only a switch made by this run counts when reading finance.env back.
    switched_before = config_points_to(config_file, args.target.resolve())
    try:
        migrate(args.repo_root, args.target, config_file, result)
    except MigrationError as exc:
        print(f"  {exc}", file=sys.stderr)
        print("  Your data was not changed and stays in the program folder.", file=sys.stderr)
        return exc.exit_code
    except BaseException as exc:  # noqa: BLE001 — incl. Ctrl+C: what matters is whether the switch happened
        # The flag can lag behind the file by a few instructions; finance.env
        # on disk is the truth.
        if not result.switched and not switched_before and config_points_to(config_file, result.target):
            result.switched = True
        if result.switched:
            try:
                (result.target / MARKER_NAME).unlink(missing_ok=True)
            except OSError:
                pass
        if not result.switched:
            print(f"  Moving the data failed: {exc!r}", file=sys.stderr)
            print("  The program folder still holds your complete data, and the app keeps using it.",
                  file=sys.stderr)
            return EXIT_FAILED
        print(f"  The data was moved to {result.target}, but cleaning up the old copy stopped: {exc!r}",
              file=sys.stderr)
        # Exit 0: the installer must treat the move as done (finance.env
        # already points to the new folder).

    if not result.switched:
        print("  Nothing to move: there is no old database in the program folder.")
        return 0
    print(f"  Database and {result.copied_files} file(s) copied to {result.target} and verified.")
    for path in result.kept_files:
        print(f"  Not moved (a different file of that name is already there): {path}")
    for path in result.leftover_files:
        print(f"  Could not delete the old copy (it is no longer used): {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
