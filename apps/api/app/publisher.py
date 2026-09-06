"""Publish complete, immutable dashboard versions before switching the manifest."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import signal
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .config import get_settings
from .monitoring import Heartbeat
from .snapshot import PAGE_SIZE, Snapshot, build_snapshot

logger = logging.getLogger("tuskometr.publisher")


def write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))
        file.flush()
        os.fsync(file.fileno())


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish(snapshot: Snapshot, root: Path, stale_seconds: float = 120) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    versions = root / "versions"
    versions.mkdir(exist_ok=True)
    version = uuid.uuid4().hex
    staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
    # mkdtemp is private by default; the static web container needs read access.
    staging.chmod(0o755)
    manifest_tmp = root / f".manifest-{version}.tmp"
    manifest = {
        "version": version,
        "generatedAt": snapshot.generated_at.isoformat(),
        "staleAfterSeconds": stale_seconds,
        "dashboards": {},
    }
    try:
        for days, items in snapshot.occurrences.items():
            base = json.loads(snapshot.dashboards[days])
            pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
            prefix = f"/dashboard/versions/{version}/{days}"
            manifest["dashboards"][str(days)] = f"{prefix}-0.json"
            for page in range(pages):
                selected = items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
                payload = {
                    **base,
                    "occurrences": {
                        "items": [item.model_dump(mode="json", by_alias=True) for item in selected],
                        "nextPage": f"{prefix}-{page + 1}.json" if page + 1 < pages else None,
                    },
                }
                write_json(staging / f"{days}-{page}.json", payload)
        sync_directory(staging)
        os.replace(staging, versions / version)
        sync_directory(versions)
        write_json(manifest_tmp, manifest)
        os.replace(manifest_tmp, root / "manifest.json")
        sync_directory(root)
    finally:
        # These paths belong exclusively to this publish attempt.
        if staging.exists():
            shutil.rmtree(staging)
        manifest_tmp.unlink(missing_ok=True)
    return manifest


def cleanup(root: Path, current_version: str, retention_seconds: float) -> None:
    cutoff = time.time() - retention_seconds
    for path in (root / "versions").iterdir():
        if (
            re.fullmatch(r"[a-f0-9]{32}", path.name)
            and path.name != current_version
            and not path.is_symlink()
            and path.is_dir()
            and path.stat().st_mtime < cutoff
        ):
            shutil.rmtree(path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    heartbeat = Heartbeat(settings.healthchecks_publishing_url.get_secret_value(), "publishing")
    root = settings.dashboard_output_dir
    root.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    with (root / ".publisher.lock").open("w") as lock:
        # A single publisher owns this output volume, even if accidentally scaled.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        remote = None
        if settings.dashboard_storage == "r2":
            from .r2_publisher import R2Publisher

            remote = R2Publisher(settings)
        while not stop.is_set():
            try:
                snapshot = build_snapshot(settings)
                if remote is not None:
                    manifest = remote.publish(snapshot)
                else:
                    manifest = publish(snapshot, root, settings.dashboard_max_stale_seconds)
                    cleanup(root, manifest["version"], settings.dashboard_retention_seconds)
                logger.info("Opublikowano dashboard %s", manifest["version"])
                heartbeat.ping()
            except Exception:
                logger.exception("Publikacja nie powiodła się; poprzednie pliki pozostają dostępne")
            stop.wait(settings.dashboard_refresh_seconds)


if __name__ == "__main__":
    main()
