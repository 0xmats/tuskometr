import json
import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.models import Base, Occurrence, PipelineState, SourceSession
from app.publisher import cleanup, publish
from app.snapshot import build_snapshot


@pytest.fixture
def database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with factory() as db:
        source = SourceSession(
            source_type="youtube",
            source_url="https://www.youtube.com/watch?v=test",
            started_at=now - timedelta(hours=1),
            status="live",
        )
        db.add(source)
        db.flush()
        db.add_all(
            [
                Occurrence(
                    source_session_id=source.id,
                    occurred_at=now - timedelta(minutes=20),
                    source_sample=100,
                    form="Tusk",
                    normalized_form="tusk",
                    quote="Donald Tusk zabrał głos",
                    confidence=0.94,
                    source_position_seconds=12.5,
                ),
                Occurrence(
                    source_session_id=source.id,
                    occurred_at=now - timedelta(minutes=10),
                    source_sample=200,
                    form="Tuska",
                    normalized_form="tuska",
                    quote="wypowiedź Donalda Tuska",
                    confidence=0.9,
                    source_position_seconds=22.5,
                ),
            ]
        )
        db.add(
            PipelineState(
                id=1,
                state="live",
                reconnect_count=2,
                lag_seconds=31,
                model_name="small",
                last_audio_at=now,
                last_error="internal diagnostic message",
                updated_at=now,
            )
        )
        db.commit()

    reads = []
    event.listen(engine, "before_cursor_execute", lambda *args: reads.append(args[2]))
    yield factory, reads
    engine.dispose()


def read_url(root, url):
    return json.loads((root / url.removeprefix("/dashboard/")).read_text())


def test_publication_and_reads_without_database(database, tmp_path):
    factory, reads = database
    snapshot = build_snapshot(Settings(_env_file=None), factory)
    assert len(reads) == 3
    manifest = publish(snapshot, tmp_path)
    reads.clear()
    for _ in range(100):
        loaded = json.loads((tmp_path / "manifest.json").read_text())
        page = read_url(tmp_path, loaded["dashboards"]["7"])
        assert page["stats"]["range"]["total"] == 2
        assert page["occurrences"]["items"][0]["form"] == "Tuska"
        assert page["occurrences"]["items"][0]["sourcePositionSeconds"] == 22.5
        assert page["status"]["message"] is None
        assert page["status"]["state"] == "live"
    assert reads == []
    assert manifest["staleAfterSeconds"] == 120


def test_failed_publication_does_not_replace_manifest(database, tmp_path, monkeypatch):
    snapshot = build_snapshot(Settings(_env_file=None), database[0])
    first = publish(snapshot, tmp_path)
    original = (tmp_path / "manifest.json").read_bytes()
    from app import publisher

    original_write = publisher.write_json

    def fail(path, payload):
        if path.name == "7-0.json":
            raise OSError("disk full")
        original_write(path, payload)

    monkeypatch.setattr(publisher, "write_json", fail)
    with pytest.raises(OSError):
        publish(snapshot, tmp_path)
    assert (tmp_path / "manifest.json").read_bytes() == original
    assert read_url(tmp_path, first["dashboards"]["1"])["stats"]["range"]["total"] == 2
    assert not list(tmp_path.glob(".pending-*"))


def test_manifest_is_switched_only_after_all_pages_exist(database, tmp_path, monkeypatch):
    snapshot = build_snapshot(Settings(_env_file=None), database[0])
    first = publish(snapshot, tmp_path)
    replace = os.replace

    def inspect(source, destination):
        if destination.name == "manifest.json":
            assert json.loads(destination.read_text()) == first
            new = json.loads(source.read_text())
            for url in new["dashboards"].values():
                assert read_url(tmp_path, url)["generatedAt"]
        return replace(source, destination)

    monkeypatch.setattr("app.publisher.os.replace", inspect)
    second = publish(snapshot, tmp_path)
    assert second["version"] != first["version"]


def test_versioned_pagination_stays_consistent(database, tmp_path):
    factory, _ = database
    with factory() as db:
        db.add_all(
            [
                Occurrence(
                    source_session_id=1,
                    occurred_at=datetime.now(UTC),
                    source_sample=1000 + i,
                    form="Tusk",
                    normalized_form="tusk",
                    quote="Tusk",
                    confidence=0.9,
                )
                for i in range(65)
            ]
        )
        db.commit()
    config = Settings(_env_file=None)
    first = publish(build_snapshot(config, factory), tmp_path)
    old_page = read_url(tmp_path, first["dashboards"]["7"])
    second = publish(build_snapshot(config, factory), tmp_path)
    assert second["version"] != first["version"]
    ids = []
    page = old_page
    while True:
        ids.extend(item["id"] for item in page["occurrences"]["items"])
        next_page = page["occurrences"]["nextPage"]
        if next_page is None:
            break
        assert first["version"] in next_page
        page = read_url(tmp_path, next_page)
    assert len(ids) == 67
    assert len(set(ids)) == 67
    assert ids == sorted(ids, reverse=True)


def test_cleanup_keeps_current_and_recent_versions(database, tmp_path):
    snapshot = build_snapshot(Settings(_env_file=None), database[0])
    old = publish(snapshot, tmp_path)
    recent = publish(snapshot, tmp_path)
    current = publish(snapshot, tmp_path)
    for version in (old["version"], current["version"]):
        path = tmp_path / "versions" / version
        os.utime(path, (time.time() - 2000, time.time() - 2000))
    cleanup(tmp_path, current["version"], 900)
    assert not (tmp_path / "versions" / old["version"]).exists()
    assert (tmp_path / "versions" / recent["version"]).exists()
    assert (tmp_path / "versions" / current["version"]).exists()


def test_rolling_window_and_stopped_worker(database):
    snapshot = build_snapshot(
        Settings(_env_file=None),
        database[0],
        now=datetime.now(UTC) + timedelta(days=2),
    )
    assert snapshot.page(1).items == []
    assert len(snapshot.page(7).items) == 2
    assert json.loads(snapshot.stats[1])["summary"]["last24Hours"] == 0
    assert json.loads(snapshot.status)["state"] == "offline"


def test_empty_database_still_produces_valid_files(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    snapshot = build_snapshot(Settings(_env_file=None), factory)
    manifest = publish(snapshot, tmp_path)
    for url in manifest["dashboards"].values():
        page = read_url(tmp_path, url)
        assert page["occurrences"] == {"items": [], "nextPage": None}
        assert page["stats"]["range"]["total"] == 0
        assert page["status"]["state"] == "offline"
    engine.dispose()


@pytest.mark.parametrize("age_days", [29, 30, 45])
def test_history_start_survives_chart_window(database, age_days):
    from sqlalchemy import select

    factory, _ = database
    now = datetime.now(UTC)
    oldest = now - timedelta(days=age_days)
    with factory() as db:
        occurrence = db.scalar(select(Occurrence).order_by(Occurrence.id).limit(1))
        occurrence.occurred_at = oldest
        db.commit()
    snapshot = build_snapshot(Settings(_env_file=None), factory, now=now)
    for days in (1, 7, 30):
        stats = json.loads(snapshot.stats[days])
        assert datetime.fromisoformat(stats["historyStartedAt"].replace("Z", "+00:00")) == oldest


@pytest.mark.parametrize("seconds_ago, expected", [(3599, 1), (3600, 1), (3601, 0), (-1, 0)])
def test_hourly_count_boundaries(database, seconds_ago, expected):
    from sqlalchemy import select

    factory, _ = database
    now = datetime.now(UTC)
    with factory() as db:
        rows = list(db.scalars(select(Occurrence).order_by(Occurrence.id)))
        rows[0].occurred_at = now - timedelta(seconds=seconds_ago)
        rows[1].occurred_at = now - timedelta(hours=2)
        db.commit()
    snapshot = build_snapshot(Settings(_env_file=None), factory, now=now)
    for days in (1, 7, 30):
        assert json.loads(snapshot.stats[days])["summary"]["lastHour"] == expected
