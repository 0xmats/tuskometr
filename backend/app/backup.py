from __future__ import annotations

import logging
import os
import signal
import sqlite3
import time
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
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"tuskometr-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.db"
    with sqlite3.connect(source_path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    snapshots = sorted(backup_dir.glob("tuskometr-*.db"), reverse=True)
    for expired in snapshots[keep:]:
        expired.unlink()
    return destination


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

    while running:
        try:
            snapshot = create_snapshot(source, backup_dir, keep)
            logger.info("Utworzono snapshot %s", snapshot)
        except FileNotFoundError:
            logger.warning("Baza jeszcze nie istnieje: %s", source)
        except Exception:
            logger.exception("Nie udało się utworzyć snapshotu")
        delay = seconds_until_next_run()
        while running and delay > 0:
            interval = min(delay, 60)
            time.sleep(interval)
            delay -= interval


if __name__ == "__main__":
    main()
