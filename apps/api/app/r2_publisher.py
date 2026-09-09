"""Publish immutable, content-addressed JSON to R2; switch manifest last."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from itertools import groupby

from .snapshot import PAGE_SIZE, Snapshot


def encode(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


class R2Publisher:
    def __init__(self, settings, client=None):
        if not settings.r2_bucket or not settings.r2_endpoint_url:
            raise ValueError("R2_BUCKET and R2_ENDPOINT_URL are required")
        if client is None:
            import boto3
            from botocore.config import Config

            if (
                not settings.r2_access_key_id
                or not settings.r2_secret_access_key.get_secret_value()
            ):
                raise ValueError("R2 credentials are required")
            client = boto3.client(
                "s3", endpoint_url=settings.r2_endpoint_url, region_name="auto",
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
                config=Config(
                    retries={"max_attempts": 3, "mode": "standard"},
                    connect_timeout=10, read_timeout=30,
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
            )
        self.client = client
        self.bucket = settings.r2_bucket
        self.settings = settings
        settings.dashboard_output_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(settings.dashboard_output_dir / "r2-state.sqlite")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS objects "
            "(key TEXT PRIMARY KEY, last_seen REAL NOT NULL, active INTEGER NOT NULL DEFAULT 0)"
        )
        self.db.commit()
        self.last_cleanup = 0.0

    def put(self, key: str, body: bytes, cache: str):
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body,
            ContentType="application/json; charset=utf-8", CacheControl=cache,
        )

    def publish(self, snapshot: Snapshot) -> dict:
        now = time.time()
        # Keep the previously published graph alive even across failed publications.
        self.db.execute("UPDATE objects SET last_seen=? WHERE active=1", (now,))
        self.db.commit()
        referenced = set()

        def immutable(payload):
            body = encode(payload)
            key = f"dashboard/objects/{hashlib.sha256(body).hexdigest()}.json"
            referenced.add(key)
            if not self.db.execute("SELECT 1 FROM objects WHERE key=?", (key,)).fetchone():
                self.put(key, body, "public, max-age=31536000, immutable")
                self.db.execute("INSERT INTO objects VALUES (?, ?, 0)", (key, now))
                self.db.commit()
            return "/" + key

        record_pages = [
            immutable({"items": [item.model_dump(mode="json", by_alias=True) for item in group]})
            for _, group in groupby(snapshot.record_items, lambda item: item.id // PAGE_SIZE)
        ]
        dashboards = {}
        for days, items in snapshot.occurrences.items():
            # Preserve time order, grouping contiguous IDs to reuse unchanged objects.
            groups = [list(group) for _, group in groupby(items, lambda item: item.id // PAGE_SIZE)]
            history = [
                immutable({
                    "items": [item.model_dump(mode="json", by_alias=True) for item in group]
                })
                for group in groups[1:]
            ]
            payload = json.loads(snapshot.dashboards[days])
            payload["recordPages"] = record_pages
            payload["occurrences"] = {
                "items": [item.model_dump(mode="json", by_alias=True) for item in groups[0]]
                if groups else [],
                "nextPage": None,
            }
            payload["historyPages"] = history
            payload["bucketPages"] = {
                start: [immutable({"items": [item.model_dump(mode="json", by_alias=True)
                                            for item in group]})
                        for _, group in groupby(selected, lambda item: item.id // PAGE_SIZE)]
                for start, selected in snapshot.bucket_items(days).items()
            }
            dashboards[str(days)] = immutable(payload)
        manifest = {
            "version": hashlib.sha256(encode(dashboards)).hexdigest(),
            "generatedAt": snapshot.generated_at.isoformat(),
            "staleAfterSeconds": self.settings.dashboard_max_stale_seconds,
            "dashboards": dashboards,
            "youtubeTimeline": snapshot.youtube_timeline,
        }
        self.put("dashboard/manifest.json", encode(manifest), "public, max-age=5, must-revalidate")
        with self.db:
            self.db.execute("UPDATE objects SET active=0")
            self.db.executemany(
                "UPDATE objects SET active=1, last_seen=? WHERE key=?",
                [(now, key) for key in referenced],
            )
        # Hourly GC: no bucket listing or HEAD request for each object/refresh.
        if now - self.last_cleanup >= 3600:
            self.cleanup(now)
            self.last_cleanup = now
        return manifest

    def cleanup(self, now: float):
        expired = self.db.execute(
            "SELECT key FROM objects WHERE active=0 AND last_seen < ?",
            (now - self.settings.r2_retention_seconds,),
        ).fetchall()
        for (key,) in expired:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            with self.db:
                self.db.execute("DELETE FROM objects WHERE key=?", (key,))
