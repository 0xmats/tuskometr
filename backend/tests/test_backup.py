import sqlite3
from pathlib import Path

from app.backup import create_snapshot, database_path


def test_creates_consistent_snapshot_and_rotates(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backups = tmp_path / "backups"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE samples (value TEXT NOT NULL)")
        db.execute("INSERT INTO samples VALUES ('Tusk')")

    first = create_snapshot(source, backups, keep=1)
    second = create_snapshot(source, backups, keep=1)

    assert second.exists()
    assert len(list(backups.glob("*.db"))) == 1
    with sqlite3.connect(second) as db:
        assert db.execute("SELECT value FROM samples").fetchone() == ("Tusk",)
    assert database_path("sqlite:////data/tuskometr.db") == Path("/data/tuskometr.db")
    assert first != second
    assert not first.exists()


def test_snapshot_captures_wal_without_checkpoint(tmp_path):
    source = tmp_path / "live.db"
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE samples (value TEXT)")
        writer.execute("INSERT INTO samples VALUES ('committed in WAL')")
        writer.commit()
        snapshot = create_snapshot(source, tmp_path / "copies")
        with sqlite3.connect(snapshot) as restored:
            assert restored.execute("SELECT value FROM samples").fetchone()[0] == "committed in WAL"


def test_invalid_restore_never_replaces_existing_database(tmp_path):
    import pytest

    from app.backup import restore_snapshot

    class InvalidRepository:
        def restore(self, snapshot, destination):
            destination.write_bytes(b"broken sqlite")

    target = tmp_path / "restored.db"
    with pytest.raises(sqlite3.DatabaseError):
        restore_snapshot(InvalidRepository(), "latest", target)
    assert not target.exists()
    target.write_bytes(b"keep existing")
    with pytest.raises(FileExistsError):
        restore_snapshot(InvalidRepository(), "latest", target)
    assert target.read_bytes() == b"keep existing"


def test_failed_remote_backup_is_reported_and_keeps_local_copy(tmp_path, monkeypatch):
    import pytest

    from app.backup import backup_once
    from app.backup_repository import Repository

    source = tmp_path / "source.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE samples (value TEXT)")
    monkeypatch.setenv("BACKUP_REMOTE_ENABLED", "true")
    monkeypatch.setenv("RESTIC_REPOSITORY", "unused")
    monkeypatch.setenv("RESTIC_PASSWORD", "test-only")
    monkeypatch.setenv("BACKUP_RESTIC_HOST", "test")

    def fail(*args):
        raise OSError("remote unavailable")

    monkeypatch.setattr(Repository, "backup", fail)
    with pytest.raises(OSError):
        backup_once(source, tmp_path / "copies", 7)
    assert len(list((tmp_path / "copies").glob("*.db"))) == 1
