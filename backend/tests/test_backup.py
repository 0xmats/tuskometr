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
