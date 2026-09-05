"""Real encrypted repository round trip; skips only if restic is not installed."""

import shutil
import sqlite3
import subprocess

import pytest

from app.backup import activate_restored, create_snapshot, restore_snapshot
from app.backup_repository import Repository


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic binary required")
def test_encrypted_repository_roundtrip_and_offline_replacement(tmp_path, monkeypatch):
    monkeypatch.setenv("RESTIC_REPOSITORY", str(tmp_path / "repository"))
    monkeypatch.setenv("RESTIC_PASSWORD", "integration-test-only")
    monkeypatch.setenv("BACKUP_RESTIC_HOST", "tuskometr-test")
    repository = Repository()
    repository.run("init")
    source = tmp_path / "live.db"
    with sqlite3.connect(source) as db:
        for table in ("source_sessions", "transcript_segments", "occurrences", "pipeline_state"):
            db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO occurrences VALUES (1, 'Tusk')")
    snapshot = create_snapshot(source, tmp_path / "copies")
    repository.backup(snapshot)
    repository.run("check", "--read-data")
    restored = tmp_path / "candidate.db"
    restore_snapshot(repository, "latest", restored)
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT value FROM occurrences").fetchone() == ("Tusk",)
    with sqlite3.connect(source) as db:
        db.execute("UPDATE occurrences SET value='newer data'")
    activate_restored(restored, source, tmp_path / "copies")
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT value FROM occurrences").fetchone() == ("Tusk",)
    safety_copy = next((tmp_path / "copies" / "before-restore").glob("*.db"))
    with sqlite3.connect(safety_copy) as db:
        assert db.execute("SELECT value FROM occurrences").fetchone() == ("newer data",)
    source.write_bytes(b"corrupt original")
    activate_restored(restored, source, tmp_path / "copies")
    raw = next((tmp_path / "copies" / "before-restore").glob("raw-*"))
    assert (raw / "live.db").read_bytes() == b"corrupt original"
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT value FROM occurrences").fetchone() == ("Tusk",)
    # Wrong password cannot produce a valid restored candidate.
    monkeypatch.setenv("RESTIC_PASSWORD", "wrong-password")
    with pytest.raises(subprocess.CalledProcessError):
        restore_snapshot(repository, "latest", tmp_path / "wrong.db")
    assert not (tmp_path / "wrong.db").exists()
