import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_publisher import database  # noqa: F401
from test_r2_publisher import Store, settings

from app.models import Occurrence, PipelineState
from app.publisher import PublicationSchedule, publish
from app.r2_publisher import R2Publisher
from app.snapshot import build_snapshot


@pytest.fixture
def clock(monkeypatch):
    current = [0.0]
    monkeypatch.setattr("app.publisher.time.monotonic", lambda: current[0])
    return current


def test_quiet_polls_do_not_write_and_periodic_refresh_updates_status(
    database, tmp_path, clock,  # noqa: F811
):
    factory, _ = database
    config = settings(tmp_path)
    store = Store()
    remote = R2Publisher(config, store)
    schedule = PublicationSchedule(config)
    first = build_snapshot(config, factory)
    schedule.publish_if_due(first, remote.publish)
    original = store.objects["dashboard/manifest.json"]["Body"]
    store.writes.clear()

    for elapsed in range(5, 65, 5):
        clock[0] = elapsed
        now = first.generated_at + timedelta(seconds=elapsed)
        # The worker keeps writing live heartbeats, lag and transcript times.
        with factory.begin() as db:
            state = db.get(PipelineState, 1)
            state.last_audio_at = now
            state.last_transcript_at = now
            state.updated_at = now
            state.lag_seconds = elapsed / 10
        snapshot = build_snapshot(config, factory, now)
        manifest = schedule.publish_if_due(snapshot, remote.publish)
        if elapsed < 60:
            assert manifest is None
            assert store.writes == []
            assert store.objects["dashboard/manifest.json"]["Body"] == original
        else:
            # Four dashboards plus manifest, reusing existing bucket objects.
            assert len(store.writes) == 5
            assert store.writes[-1] == "dashboard/manifest.json"
            page = json.loads(store.objects[manifest["dashboards"]["1"].lstrip("/")]["Body"])
            assert page["status"]["lagSeconds"] == 6
            assert page["generatedAt"] == json.loads(snapshot.dashboards[1])["generatedAt"]
            assert manifest["staleAfterSeconds"] == 120


@pytest.mark.parametrize("change", ["live", "backfill", "edit", "delete"])
def test_changed_mentions_publish_on_next_poll(database, tmp_path, clock, change):  # noqa: F811
    factory, _ = database
    config = settings(tmp_path)
    store = Store()
    remote = R2Publisher(config, store)
    schedule = PublicationSchedule(config)
    first = build_snapshot(config, factory)
    schedule.publish_if_due(first, remote.publish)
    store.writes.clear()
    with factory.begin() as db:
        row = db.scalar(select(Occurrence).order_by(Occurrence.id))
        if change in ("live", "backfill"):
            db.add(Occurrence(
                source_session_id=row.source_session_id,
                source_sample=999,
                occurred_at=first.generated_at - timedelta(days=2 if change == "backfill" else 0),
                form="Tusk", normalized_form="tusk", quote="Nowe trafienie", confidence=0.9,
            ))
        elif change == "edit":
            row.quote = "Poprawiony cytat"
        else:
            db.delete(row)
    clock[0] = 5
    changed = build_snapshot(config, factory, first.generated_at + timedelta(seconds=5))
    manifest = schedule.publish_if_due(changed, remote.publish)
    assert manifest is not None
    assert store.writes[-1] == "dashboard/manifest.json"
    page = json.loads(store.objects[manifest["dashboards"]["7"].lstrip("/")]["Body"])
    quotes = [item["quote"] for item in page["occurrences"]["items"]]
    assert len(quotes) == (3 if change in ("live", "backfill") else 1 if change == "delete" else 2)
    if change == "edit":
        assert "Poprawiony cytat" in quotes


@pytest.mark.parametrize("field, value", [
    ("state", "reconnecting"), ("model_name", "base"), ("reconnect_count", 3),
])
def test_pipeline_transitions_publish_promptly(
    database, tmp_path, clock, field, value,  # noqa: F811
):
    factory, _ = database
    config = settings(tmp_path)
    schedule = PublicationSchedule(config)
    remote = R2Publisher(config, Store())
    first = build_snapshot(config, factory)
    schedule.publish_if_due(first, remote.publish)
    with factory.begin() as db:
        setattr(db.get(PipelineState, 1), field, value)
    clock[0] = 5
    changed = build_snapshot(config, factory, first.generated_at + timedelta(seconds=5))
    assert schedule.publish_if_due(changed, remote.publish) is not None


def test_failed_periodic_upload_retries_at_next_poll(database, tmp_path, clock):  # noqa: F811
    config = settings(tmp_path)
    store = Store()
    remote = R2Publisher(config, store)
    schedule = PublicationSchedule(config)
    first = build_snapshot(config, database[0])
    schedule.publish_if_due(first, remote.publish)
    original = store.objects["dashboard/manifest.json"]["Body"]
    clock[0] = 60
    store.fail = True
    changed = build_snapshot(config, database[0], first.generated_at + timedelta(seconds=60))
    with pytest.raises(OSError, match="upload failed"):
        schedule.publish_if_due(changed, remote.publish)
    assert store.objects["dashboard/manifest.json"]["Body"] == original
    store.fail = False
    clock[0] = 65
    retry = build_snapshot(config, database[0], first.generated_at + timedelta(seconds=65))
    assert schedule.publish_if_due(retry, remote.publish) is not None
    assert store.objects["dashboard/manifest.json"]["Body"] != original


def test_refresh_respects_short_stale_threshold_and_restart(
    database, tmp_path, clock,  # noqa: F811
):
    config = settings(tmp_path)
    config.dashboard_max_stale_seconds = 30
    remote = R2Publisher(config, Store())
    schedule = PublicationSchedule(config)
    first = build_snapshot(config, database[0])
    schedule.publish_if_due(first, remote.publish)
    for elapsed in (5, 10, 15):
        clock[0] = elapsed
        snapshot = build_snapshot(
            config, database[0], first.generated_at + timedelta(seconds=elapsed),
        )
        assert (schedule.publish_if_due(snapshot, remote.publish) is not None) == (elapsed == 15)
    # A process restart does not leave an old manifest waiting for the interval.
    assert PublicationSchedule(config).publish_if_due(snapshot, remote.publish) is not None


def test_local_publication_also_skips_unchanged_polls(database, tmp_path, clock):  # noqa: F811
    config = settings(tmp_path)
    schedule = PublicationSchedule(config)
    first = build_snapshot(config, database[0])

    def write(snapshot):
        return publish(snapshot, tmp_path)

    schedule.publish_if_due(first, write)
    original = (tmp_path / "manifest.json").read_bytes()
    clock[0] = 5
    snapshot = build_snapshot(config, database[0], first.generated_at + timedelta(seconds=5))
    assert schedule.publish_if_due(snapshot, write) is None
    assert (tmp_path / "manifest.json").read_bytes() == original
    assert len(list((tmp_path / "versions").iterdir())) == 1
