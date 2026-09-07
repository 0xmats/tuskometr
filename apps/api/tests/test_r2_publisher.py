import json
from dataclasses import replace
from datetime import timedelta

import pytest
from test_publisher import backfilled_snapshot, database  # noqa: F401

from app.config import Settings
from app.r2_publisher import R2Publisher
from app.schemas import OccurrenceDto
from app.snapshot import RANGES, build_snapshot


class Store:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.fail = False

    def put_object(self, **args):
        if self.fail and args["Key"].startswith("dashboard/objects/"):
            raise OSError("upload failed")
        self.objects[args["Key"]] = args
        self.writes.append(args["Key"])

    def delete_object(self, **args):
        self.objects.pop(args["Key"], None)


def settings(path):
    return Settings(
        _env_file=None,
        dashboard_output_dir=path,
        r2_bucket="test",
        r2_endpoint_url="https://example.com",
    )


def test_deduplication_restart_and_atomic_manifest(database, tmp_path):  # noqa: F811
    store = Store()
    config = settings(tmp_path)
    publisher = R2Publisher(config, store)
    snapshot = build_snapshot(config, database[0])
    manifest = publisher.publish(snapshot)
    original = store.objects["dashboard/manifest.json"]["Body"]
    store.writes.clear()
    publisher.db.close()
    publisher = R2Publisher(config, store)
    publisher.publish(snapshot)
    assert store.writes == ["dashboard/manifest.json"]
    store.fail = True
    changed = build_snapshot(config, database[0], snapshot.generated_at + timedelta(seconds=30))
    with pytest.raises(OSError):
        publisher.publish(changed)
    assert store.objects["dashboard/manifest.json"]["Body"] == original
    for url in manifest["dashboards"].values():
        assert url.lstrip("/") in store.objects


def test_history_is_stable_on_insert_and_old_snapshot_remains_readable(database, tmp_path):  # noqa: F811
    config = settings(tmp_path)
    store = Store()
    publisher = R2Publisher(config, store)
    snapshot = build_snapshot(config, database[0])
    items = tuple(
        OccurrenceDto(
            id=i,
            occurred_at=snapshot.generated_at,
            form="Tusk",
            quote="Tusk",
            confidence=0.9,
            source_url="https://youtube.com/watch?v=test",
        )
        for i in range(120, 0, -1)
    )
    snapshot = replace(snapshot, occurrences={d: items for d in RANGES})
    first = publisher.publish(snapshot)
    old = json.loads(store.objects[first["dashboards"]["7"].lstrip("/")]["Body"])
    old_history = old["historyPages"]
    # History objects are shared across ranges; the fixture's record adds one object.
    assert (
        len({key for key in store.writes if key.startswith("dashboard/objects/")})
        == len(RANGES) + 6
    )
    store.writes.clear()
    added = items[0].model_copy(update={"id": 121})
    second = publisher.publish(replace(snapshot, occurrences={d: (added, *items) for d in RANGES}))
    new = json.loads(store.objects[second["dashboards"]["7"].lstrip("/")]["Body"])
    assert new["historyPages"] == old_history
    assert len(store.writes) == len(RANGES) + 2
    ids = [x["id"] for x in old["occurrences"]["items"]]
    for url in old_history:
        ids += [x["id"] for x in json.loads(store.objects[url.lstrip("/")]["Body"])["items"]]
    assert ids == list(range(120, 0, -1))


def test_gc_preserves_active_and_recent_objects(database, tmp_path):  # noqa: F811
    config = settings(tmp_path)
    store = Store()
    publisher = R2Publisher(config, store)
    publisher.publish(build_snapshot(config, database[0]))
    store.objects["dashboard/objects/obsolete.json"] = {}
    publisher.db.execute(
        "INSERT INTO objects VALUES (?, 0, 0)", ("dashboard/objects/obsolete.json",)
    )
    publisher.db.commit()
    publisher.cleanup(10**12)
    assert "dashboard/objects/obsolete.json" not in store.objects
    assert all(key in store.objects for (key,) in publisher.db.execute("SELECT key FROM objects"))
    assert "dashboard/manifest.json" in store.objects


def test_r2_backfill_order_and_complete_bucket_pages(backfilled_snapshot, tmp_path):  # noqa: F811
    from test_publisher import assert_bucket_pages, assert_chronological

    store = Store()
    publisher = R2Publisher(settings(tmp_path), store)
    manifest = publisher.publish(backfilled_snapshot)

    def read(url):
        return json.loads(store.objects[url.lstrip("/")]["Body"])

    dashboard = read(manifest["dashboards"]["1"])
    items = dashboard["occurrences"]["items"] + [
        item for url in dashboard["historyPages"] for item in read(url)["items"]
    ]
    assert len(items) == 72
    assert_chronological(items)
    for url in manifest["dashboards"].values():
        assert_bucket_pages(read(url), read)
