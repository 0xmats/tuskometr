"""Encrypted off-site SQLite snapshots via restic (private S3/R2 repository)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class Repository:
    def __init__(self):
        for name in ("RESTIC_REPOSITORY", "RESTIC_PASSWORD", "BACKUP_RESTIC_HOST"):
            if not os.environ.get(name):
                raise ValueError(f"Set {name}")
        self.host = os.environ["BACKUP_RESTIC_HOST"]

    def run(self, *args: str, stdout=None):
        # Credentials stay in the environment, never command arguments or logs.
        return subprocess.run(
            ["restic", "--no-cache", *args],
            check=True,
            stdout=stdout,
            timeout=3600,
        )

    def filters(self):
        return ["--host", self.host, "--tag", "tuskometr,sqlite"]

    def backup(self, snapshot: Path):
        # Snapshot has already been completed and checked. No partial stdin dump.
        with snapshot.open("rb") as stream:
            subprocess.run(
                [
                    "restic",
                    "--no-cache",
                    "backup",
                    "--stdin",
                    "--stdin-filename",
                    "/sqlite/tuskometr.db",
                    *self.filters(),
                ],
                stdin=stream,
                check=True,
                timeout=3600,
            )
        keep = []
        for option, default in (("LAST", 10), ("DAILY", 14), ("WEEKLY", 8)):
            count = int(os.getenv(f"BACKUP_RESTIC_KEEP_{option}", str(default)))
            if count < 1:
                raise ValueError("Backup retention values must be positive")
            keep.extend([f"--keep-{option.lower()}", str(count)])
        self.run("forget", *self.filters(), *keep, "--prune")

    def restore(self, snapshot: str, destination: Path):
        with destination.open("xb") as output:
            self.run("dump", *self.filters(), snapshot, "/sqlite/tuskometr.db", stdout=output)
            output.flush()
            os.fsync(output.fileno())
