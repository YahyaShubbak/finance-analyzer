"""The installer's move of pre-0.2 in-repo data (app.legacy_migration).

Every failure case asserts the same contract: until finance.env points to the
new folder, the old data is complete and untouched, because that is what the
app keeps using.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app import legacy_migration as lm


def _make_db(path: Path, rows: int = 5) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")  # as the app's own connections do
    conn.execute("CREATE TABLE transactions(id INTEGER PRIMARY KEY, amount TEXT)")
    conn.executemany("INSERT INTO transactions(amount) VALUES (?)", [(f"{i}.00",) for i in range(rows)])
    conn.commit()
    conn.close()


def _rows(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def repo(tmp_path) -> Path:
    """A checkout with the old layout: data/finance.db and the three folders."""
    root = tmp_path / "repo"
    (root / "data" / ".staging").mkdir(parents=True)
    _make_db(root / "data" / "finance.db")
    (root / "imports").mkdir()
    (root / "imports" / "statement.csv").write_text("date;amount\n2026-01-01;5\n", encoding="utf-8")
    (root / "imports" / "sub").mkdir()
    (root / "imports" / "sub" / "nested.pdf").write_bytes(b"%PDF-1.4 fake")
    (root / "imports" / ".gitkeep").write_text("", encoding="utf-8")
    (root / "backups").mkdir()
    (root / "backups" / "finance-backup.zip").write_bytes(b"PK fake zip")
    (root / "data" / ".staging" / "abc__upload.csv").write_text("x", encoding="utf-8")
    (root / "finance.env").write_text("FINANCE_PORT=8421\nFINANCE_OPEN_BROWSER=false\n", encoding="utf-8")
    return root


def _target(tmp_path) -> Path:
    return tmp_path / "new data (privat) ü"


def _assert_old_data_untouched(repo: Path) -> None:
    assert _rows(repo / "data" / "finance.db") == 5
    assert (repo / "imports" / "statement.csv").exists()
    assert (repo / "imports" / "sub" / "nested.pdf").exists()
    assert (repo / "backups" / "finance-backup.zip").exists()
    assert "FINANCE_DATA_DIR" not in dotenv_values(repo / "finance.env")


def test_moves_everything_and_switches_config(repo, tmp_path):
    target = _target(tmp_path)

    result = lm.migrate(repo, target, repo / "finance.env")

    assert _rows(target / "finance.db") == 5
    assert (target / "imports" / "statement.csv").read_text(encoding="utf-8").startswith("date;amount")
    assert (target / "imports" / "sub" / "nested.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert (target / "backups" / "finance-backup.zip").exists()
    assert (target / ".staging" / "abc__upload.csv").exists()
    assert not (target / "imports" / ".gitkeep").exists()
    assert result.copied_files == 4 and not result.kept_files and not result.leftover_files

    env = dotenv_values(repo / "finance.env")
    assert Path(env["FINANCE_DATA_DIR"]) == target.resolve()
    assert env["FINANCE_PORT"] == "8421"  # other settings are kept

    assert not (repo / "data").exists()  # emptied and removed
    assert not (repo / "backups").exists()
    assert [p.name for p in (repo / "imports").iterdir()] == [".gitkeep"]
    assert not (target / lm.MARKER_NAME).exists()
    assert not list(target.rglob("*.partial"))


def test_rows_only_in_the_wal_are_not_lost(repo, tmp_path):
    """A crash (or a kill of the app) can leave committed rows only in -wal.
    A file-by-file move that dropped or misordered -wal would lose them."""
    db = repo / "data" / "finance.db"
    db.unlink()
    writer = sqlite3.connect(tmp_path / "live.db")
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE transactions(id INTEGER PRIMARY KEY, amount TEXT)")
    writer.executemany("INSERT INTO transactions(amount) VALUES (?)", [("1.00",)] * 7)
    writer.commit()
    for suffix in ("", "-wal"):  # snapshot of the files as a crash leaves them
        shutil.copyfile(f"{tmp_path / 'live.db'}{suffix}", f"{db}{suffix}")
    writer.close()
    assert Path(f"{db}-wal").stat().st_size > 0

    lm.migrate(repo, _target(tmp_path), repo / "finance.env")

    assert _rows(_target(tmp_path) / "finance.db") == 7


def test_refuses_while_the_database_is_open(repo, tmp_path):
    app_connection = sqlite3.connect(repo / "data" / "finance.db")
    app_connection.execute("PRAGMA journal_mode=WAL")
    app_connection.execute("SELECT 1 FROM transactions").fetchall()  # open but idle, like the app's pool
    try:
        with pytest.raises(lm.DatabaseInUseError):
            lm.migrate(repo, _target(tmp_path), repo / "finance.env")
    finally:
        app_connection.close()

    _assert_old_data_untouched(repo)
    assert not (_target(tmp_path) / "finance.db").exists()


def test_refuses_while_the_app_runs_without_an_open_connection(repo, tmp_path):
    """Found in an end-to-end run: an app that has not touched the database
    yet holds no SQLite connection, but has the old folder in memory and
    would create a new, empty database there. Its instance lock gives it
    away."""
    from tests.test_instance_lock import hold_lock_in_another_process

    app_process = hold_lock_in_another_process(repo / "data")
    try:
        with pytest.raises(lm.DatabaseInUseError, match="running"):
            lm.migrate(repo, _target(tmp_path), repo / "finance.env")
    finally:
        app_process.kill()
        app_process.wait()

    _assert_old_data_untouched(repo)
    assert not (_target(tmp_path) / "finance.db").exists()


def test_the_app_cannot_start_during_the_move(repo, tmp_path, monkeypatch):
    from app import instance_lock

    seen = {}
    real_copy = lm._copy_file

    def copy_and_try_to_start_the_app(src, dst):
        try:
            instance_lock.release(instance_lock.acquire(repo / "data"))
            seen["app could start"] = True
        except instance_lock.AlreadyLockedError:
            seen["app could start"] = False
        real_copy(src, dst)

    monkeypatch.setattr(lm, "_copy_file", copy_and_try_to_start_the_app)
    lm.migrate(repo, _target(tmp_path), repo / "finance.env")

    assert seen == {"app could start": False}


def test_refuses_a_foreign_database_in_the_target(repo, tmp_path):
    target = _target(tmp_path)
    target.mkdir()
    _make_db(target / "finance.db", rows=2)

    with pytest.raises(lm.TargetHasDatabaseError):
        lm.migrate(repo, target, repo / "finance.env")

    assert _rows(target / "finance.db") == 2  # not overwritten
    _assert_old_data_untouched(repo)


def test_resumes_after_an_interrupted_run(repo, tmp_path):
    """A run that stopped before switching finance.env leaves its marker; the
    database it left in the target is its own and may be replaced."""
    target = _target(tmp_path)
    target.mkdir()
    _make_db(target / "finance.db", rows=1)  # stale, incomplete copy
    (target / "imports").mkdir()
    shutil.copy2(repo / "imports" / "statement.csv", target / "imports" / "statement.csv")
    (target / lm.MARKER_NAME).write_text(json.dumps({"source": str(repo.resolve())}), encoding="utf-8")

    result = lm.migrate(repo, target, repo / "finance.env")

    assert _rows(target / "finance.db") == 5
    assert not result.kept_files  # the identical earlier copy counts as copied
    assert not (repo / "imports" / "statement.csv").exists()
    assert not (target / lm.MARKER_NAME).exists()


def test_a_failed_copy_leaves_the_old_data_in_use(repo, tmp_path, monkeypatch, capsys):
    calls = {"n": 0}
    real_copy = lm._copy_file

    def failing_copy(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(28, "No space left on device")
        real_copy(src, dst)

    monkeypatch.setattr(lm, "_copy_file", failing_copy)

    code = lm.main(["--repo-root", str(repo), "--target", str(_target(tmp_path))])

    assert code == lm.EXIT_FAILED
    assert "still holds your complete data" in capsys.readouterr().err
    _assert_old_data_untouched(repo)
    assert (repo / "data" / ".staging" / "abc__upload.csv").exists()


def test_a_write_during_the_copy_is_detected(repo, tmp_path, monkeypatch):
    real_copy = lm._copy_file

    def copy_while_the_app_writes(src, dst):
        conn = sqlite3.connect(repo / "data" / "finance.db")
        conn.execute("INSERT INTO transactions(amount) VALUES ('9.99')")
        conn.commit()
        conn.close()
        real_copy(src, dst)

    monkeypatch.setattr(lm, "_copy_file", copy_while_the_app_writes)

    with pytest.raises(lm.DatabaseInUseError):
        lm.migrate(repo, _target(tmp_path), repo / "finance.env")

    assert "FINANCE_DATA_DIR" not in dotenv_values(repo / "finance.env")
    assert _rows(repo / "data" / "finance.db") > 5  # the new row is in the data still in use


def test_a_different_file_in_the_target_is_kept_not_overwritten(repo, tmp_path):
    target = _target(tmp_path)
    (target / "imports").mkdir(parents=True)
    (target / "imports" / "statement.csv").write_text("someone else's file", encoding="utf-8")

    result = lm.migrate(repo, target, repo / "finance.env")

    assert (target / "imports" / "statement.csv").read_text(encoding="utf-8") == "someone else's file"
    assert (repo / "imports" / "statement.csv").exists()  # original kept
    assert result.kept_files == [repo.resolve() / "imports" / "statement.csv"]


@pytest.mark.parametrize("inside", [".", "backups", "imports/new", "data/.staging"])
def test_refuses_a_target_inside_the_program_folder(repo, inside):
    """Found in review: with the repo root as target, imports/x is its own
    "identical copy" and was deleted; inside backups/, the fresh database
    copy was itself picked up as an old file."""
    with pytest.raises(lm.MigrationError, match="inside the program folder"):
        lm.migrate(repo, repo / inside, repo / "finance.env")
    _assert_old_data_untouched(repo)


def test_an_interruption_after_the_switch_is_reported_as_done(repo, tmp_path, monkeypatch, capsys):
    """Ctrl+C (or any error) while deleting the originals: finance.env already
    points to the new folder, so the installer must not be told "not moved"."""
    def interrupted(_repo_root):
        raise KeyboardInterrupt

    monkeypatch.setattr(lm, "_remove_empty_dirs", interrupted)
    target = _target(tmp_path)

    code = lm.main(["--repo-root", str(repo), "--target", str(target)])

    assert code == 0
    err = capsys.readouterr().err
    assert "was moved to" in err and "still holds" not in err
    assert Path(dotenv_values(repo / "finance.env")["FINANCE_DATA_DIR"]) == target.resolve()
    assert _rows(target / "finance.db") == 5
    assert not (target / lm.MARKER_NAME).exists()  # gone with the switch, not only at the very end


def test_no_marker_survives_the_switch_so_the_live_db_is_never_resumed_over(repo, tmp_path, monkeypatch):
    """Found in review: a marker left after a successful switch made a later
    run (old data restored into the checkout) overwrite the live database."""
    monkeypatch.setattr(lm, "_remove_empty_dirs", lambda _root: (_ for _ in ()).throw(KeyboardInterrupt()))
    target = _target(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        lm.migrate(repo, target, repo / "finance.env")
    monkeypatch.undo()

    _make_db(repo / "data" / "finance.db", rows=1)  # an old copy shows up again
    (repo / "finance.env").write_text("", encoding="utf-8")

    with pytest.raises(lm.TargetHasDatabaseError):
        lm.migrate(repo, target, repo / "finance.env")
    assert _rows(target / "finance.db") == 5


def test_a_failed_config_switch_leaves_the_originals(repo, tmp_path, monkeypatch, capsys):
    """Found in review: moving the deletion of the originals before the
    switch passed every test. The originals must survive any failure up to
    and including writing finance.env."""
    def disk_full(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(lm, "set_config_value", disk_full)

    assert lm.main(["--repo-root", str(repo), "--target", str(_target(tmp_path))]) == lm.EXIT_FAILED
    assert "still holds your complete data" in capsys.readouterr().err
    _assert_old_data_untouched(repo)
    assert (repo / "data" / ".staging" / "abc__upload.csv").exists()


def test_an_interruption_right_after_the_replace_counts_as_moved(repo, tmp_path, monkeypatch, capsys):
    """Found in review: an error between os.replace (finance.env switched)
    and recording the switch was reported as "not moved" and left the marker
    behind, which a later run would take as licence to overwrite the live
    database. finance.env on disk decides."""
    real_replace = lm.os.replace

    def replace_then_interrupt(src, dst):
        real_replace(src, dst)
        if Path(dst).name == "finance.env":
            raise KeyboardInterrupt

    monkeypatch.setattr(lm.os, "replace", replace_then_interrupt)
    target = _target(tmp_path)

    assert lm.main(["--repo-root", str(repo), "--target", str(target)]) == 0
    err = capsys.readouterr().err
    assert "was moved to" in err and "still holds" not in err
    assert not (target / lm.MARKER_NAME).exists()
    assert _rows(target / "finance.db") == 5


def test_a_failing_directory_fsync_does_not_undo_the_switch(repo, tmp_path, monkeypatch):
    real_fsync_dir = lm._fsync_dir

    def fsync_dir(path):
        if path == repo.resolve():  # the folder holding finance.env
            raise OSError(22, "fsync not supported on this mount")
        real_fsync_dir(path)

    monkeypatch.setattr(lm, "_fsync_dir", fsync_dir)
    result = lm.migrate(repo, _target(tmp_path), repo / "finance.env")
    assert result.switched
    assert not (repo / "data" / "finance.db").exists()


def test_nothing_to_do_without_an_old_database(tmp_path):
    (tmp_path / "repo").mkdir()
    result = lm.migrate(tmp_path / "repo", tmp_path / "target", tmp_path / "repo" / "finance.env")
    assert result.copied_files == 0
    assert not (tmp_path / "target").exists()
    assert not (tmp_path / "repo" / "finance.env").exists()


def test_the_app_ignores_the_installers_keep_marker(tmp_path, monkeypatch):
    """install.sh/.ps1 write FINANCE_KEEP_DATA_IN_PROGRAM_FOLDER=true when the
    user keeps the old layout; the app's settings must load with it present."""
    from app.config import Settings

    for name in ("FINANCE_DATA_DIR", "FINANCE_PORT"):  # environment beats the file
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / "finance.env"
    env.write_text("FINANCE_KEEP_DATA_IN_PROGRAM_FOLDER=true\nFINANCE_PORT=8433\n", encoding="utf-8")

    loaded = Settings(_env_file=env)

    assert loaded.port == 8433
    assert not hasattr(loaded, "keep_data_in_program_folder")


@pytest.mark.parametrize("folder", ["Max's Daten", "C:\\Users\\Jürgen (Privat)\\finance", "/home/o'neil/data dir"])
def test_written_value_reads_back_with_python_dotenv(tmp_path, folder):
    """The app reads finance.env with python-dotenv (via pydantic-settings)."""
    env = tmp_path / "finance.env"
    lm.set_config_value(env, "FINANCE_DATA_DIR", folder)
    expected = folder.replace("\\", "/") if lm.os.name == "nt" else folder
    assert dotenv_values(env)["FINANCE_DATA_DIR"] == expected
