from __future__ import annotations

import argparse
import fcntl
import logging
import os
import shutil
import signal
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import get_settings

logger = logging.getLogger("tuskometr.backup")
running = True


def database_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("Automatyczne snapshoty obsługują wyłącznie SQLite")
    return Path(database_url.removeprefix(prefix))


def create_snapshot(source_path: Path, backup_dir: Path, keep: int = 7) -> Path:
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if keep < 1:
        raise ValueError("keep must be positive")
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"tuskometr-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.db"
    pending = destination.with_suffix(".pending")
    try:
        with closing(
            sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
        ) as source:
            with closing(sqlite3.connect(pending)) as target:
                source.backup(target)
                target.execute("PRAGMA journal_mode=DELETE")
        validate_database(pending)
        os.chmod(pending, 0o600)
        with pending.open("rb") as file:
            os.fsync(file.fileno())
        os.replace(pending, destination)
    finally:
        pending.unlink(missing_ok=True)
    snapshots = sorted(backup_dir.glob("tuskometr-*.db"), reverse=True)
    for expired in snapshots[keep:]:
        expired.unlink()
    return destination


def validate_database(path: Path, require_schema: bool = False) -> None:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("SQLite foreign key check failed")
        if require_schema:
            tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            required = {"source_sessions", "transcript_segments", "occurrences", "pipeline_state"}
            if not required <= tables:
                raise ValueError("Snapshot is not a Tuskometr database")


def restore_snapshot(repository, snapshot: str, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError("Restore destination already exists; choose a new filename")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        candidate = Path(directory) / "restored.db"
        repository.restore(snapshot, candidate)
        validate_database(candidate, require_schema=True)
        os.chmod(candidate, 0o600)
        # Hard link is atomic and refuses an existing destination (no overwrite race).
        os.link(candidate, destination)


def activate_restored(candidate: Path, target: Path, backup_dir: Path) -> None:
    """Offline only: callers must stop every database reader/writer first."""
    if candidate.resolve() == target.resolve():
        raise ValueError("Candidate must differ from the live database")
    validate_database(candidate, require_schema=True)
    if target.exists():
        try:
            create_snapshot(target, backup_dir / "before-restore", keep=7)
        except (sqlite3.DatabaseError, ValueError):
            # Recovery must also work when the current database is corrupt.
            # Offline raw copies preserve all evidence, including any WAL.
            raw_dir = (
                backup_dir / "before-restore" / datetime.now(UTC).strftime("raw-%Y%m%d-%H%M%S-%f")
            )
            raw_dir.mkdir(parents=True, mode=0o700)
            for suffix in ("", "-wal", "-shm"):
                original = Path(str(target) + suffix)
                if original.exists():
                    saved = raw_dir / original.name
                    shutil.copy2(original, saved)
                    os.chmod(saved, 0o600)
            logger.warning("Corrupt original preserved in %s", raw_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as directory:
        staged = create_snapshot(candidate, Path(directory))
        # The replacement is self-contained; stale WAL must never replay over it.
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        os.replace(staged, target)


def backup_once(source: Path, backup_dir: Path, keep: int) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    with (backup_dir / ".backup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshot = create_snapshot(source, backup_dir, keep)
        if os.getenv("BACKUP_REMOTE_ENABLED", "false").lower() == "true":
            from .backup_repository import Repository

            Repository().backup(snapshot)
        logger.info("Backup completed: %s", snapshot.name)
        return snapshot


def seconds_until_next_run(hour: int = 3, minute: int = 30) -> float:
    now = datetime.now(UTC)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def stop(_signum, _frame) -> None:
    global running
    running = False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    settings = get_settings()
    source = database_path(settings.database_url)
    backup_dir = Path(os.getenv("BACKUP_DIR", "/backups"))
    keep = int(os.getenv("BACKUP_KEEP", "7"))

    parser = argparse.ArgumentParser(description="SQLite local and encrypted off-site backups")
    parser.add_argument(
        "action",
        nargs="?",
        default="daemon",
        choices=["daemon", "once", "init", "list", "check", "restore", "activate"],
    )
    parser.add_argument("--snapshot", default="latest")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.action == "activate":
        if not args.offline or args.output is None:
            parser.error("activate requires --offline and --output PATH (restored candidate)")
        activate_restored(args.output, source, backup_dir)
        return
    if args.action in {"init", "list", "check", "restore"}:
        from .backup_repository import Repository

        repository = Repository()
        if args.action == "restore":
            if args.output is None:
                parser.error("restore requires --output PATH")
            if args.output.resolve() == source.resolve():
                parser.error("restore into a separate file first; use the offline restore script")
            restore_snapshot(repository, args.snapshot, args.output)
        elif args.action == "list":
            repository.run("snapshots", *repository.filters())
        elif args.action == "check":
            repository.run("check", "--read-data")
        else:
            repository.run("init")
        return
    if args.action == "once":
        backup_once(source, backup_dir, keep)
        return
    while running:
        success = False
        try:
            backup_once(source, backup_dir, keep)
            success = True
        except FileNotFoundError:
            logger.warning("Baza jeszcze nie istnieje: %s", source)
        except Exception:
            logger.exception("Nie udało się utworzyć snapshotu")
        # Retry failed off-site copies in five minutes, not the next day.
        delay = seconds_until_next_run() if success else 300
        while running and delay > 0:
            interval = min(delay, 60)
            time.sleep(interval)
            delay -= interval


if __name__ == "__main__":
    main()
