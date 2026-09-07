import json
import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_publisher import database  # noqa: F401
from test_r2_publisher import Store, settings

from app.models import Occurrence, TranscriptSegment
from app.publisher import publication_signature, publish
from app.r2_publisher import R2Publisher
from app.snapshot import build_snapshot, find_hourly_record

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


@pytest.mark.parametrize("seconds, count, end", [
    ([], 0, None), ([0], 1, 0), ([0, 3600], 2, 3600),
    ([0, 3600.001], 1, 0), ([0, 0, 0, 3600, 3600], 5, 3600),
    ([0, 10, 7200, 7210], 2, 10),
])
def test_closed_rolling_window_boundaries_duplicates_and_earliest_tie(seconds, count, end):
    record = find_hourly_record(NOW + timedelta(seconds=value) for value in seconds)
    if not count:
        assert record is None
    else:
        assert record.count == count
        assert record.end == NOW + timedelta(seconds=end)
        assert record.end - record.start == timedelta(hours=1)


def test_rolling_scan_matches_brute_force():
    rng = random.Random(123)
    for _ in range(30):
        times = sorted(NOW + timedelta(seconds=rng.randrange(20000)) for _ in range(120))
        expected_count, expected_end = max(
            ((sum(end - timedelta(hours=1) <= at <= end for at in times), end) for end in times),
            key=lambda item: (item[0], -item[1].timestamp()),
        )
        record = find_hourly_record(iter(times))
        assert (record.count, record.end) == (expected_count, expected_end)


@pytest.fixture
def old_record(database):  # noqa: F811
    factory, _ = database
    start = NOW - timedelta(days=40)
    with factory.begin() as db:
        db.query(Occurrence).delete()
        for index in range(65):
            db.add(Occurrence(
                source_session_id=1, source_sample=index,
                occurred_at=start + timedelta(seconds=index * 50),
                form="Tusk", normalized_form="tusk", quote=f"Archiwalna wzmianka {index}",
                confidence=0.9,
            ))
        db.add(Occurrence(
            source_session_id=1, source_sample=99999, occurred_at=NOW - timedelta(minutes=1),
            form="Tusk", normalized_form="tusk", quote="Bieżąca wzmianka", confidence=0.9,
        ))
        # Earlier successful audio with no mentions determines measurement age.
        db.add(TranscriptSegment(
            source_session_id=1, start_sample=0, end_sample=100,
            started_at=start - timedelta(hours=1), ended_at=start - timedelta(minutes=59),
            text="Wiadomości", checksum="test", expires_at=NOW + timedelta(days=1),
        ))
    return factory


@pytest.mark.parametrize("storage", ["local", "r2"])
def test_record_outside_chart_range_publishes_every_fragment(old_record, tmp_path, storage):
    config = settings(tmp_path)
    snapshot = build_snapshot(config, old_record, NOW)
    assert len(snapshot.occurrences[30]) == 1
    assert len(snapshot.record_items) == 65
    store = Store()
    if storage == "local":
        manifest = publish(snapshot, tmp_path)

        def read(url):
            return json.loads((tmp_path / url.removeprefix("/dashboard/")).read_text())
    else:
        remote = R2Publisher(config, store)
        manifest = remote.publish(snapshot)

        def read(url):
            return json.loads(store.objects[url.lstrip("/")]["Body"])

    record_urls = None
    for url in manifest["dashboards"].values():
        page = read(url)
        record = page["stats"]["hourlyRecord"]
        assert record["count"] == 65
        assert page["stats"]["summary"]["lastHour"] == 1
        expected_start = NOW - timedelta(days=40, hours=1)
        assert datetime.fromisoformat(page["stats"]["historyStartedAt"]) == expected_start
        items = [item for record_url in page["recordPages"] for item in read(record_url)["items"]]
        assert [item["id"] for item in items] == [item.id for item in snapshot.record_items]
        assert len({item["id"] for item in items}) == record["count"]
        assert all(record["start"] <= item["occurredAt"] <= record["end"] for item in items)
        assert record_urls is None or page["recordPages"] == record_urls
        record_urls = page["recordPages"]
    if storage == "r2":
        store.writes.clear()
        remote.publish(build_snapshot(config, old_record, NOW + timedelta(minutes=1)))
        assert not set(store.writes).intersection(url.lstrip("/") for url in record_urls)
        # GC must keep an all-time record even though it is older than 30 days.
        remote.cleanup(10**12)
        assert all(read(url)["items"] for url in record_urls)


def test_old_backfill_corrections_and_future_times(old_record, tmp_path):
    config = settings(tmp_path)
    first = build_snapshot(config, old_record, NOW)
    with old_record.begin() as db:
        row = db.scalar(select(Occurrence).where(Occurrence.occurred_at < NOW - timedelta(days=30)))
        row.quote = "Poprawiony stary cytat"
    edited = build_snapshot(config, old_record, NOW)
    assert publication_signature(first) != publication_signature(edited)
    with old_record.begin() as db:
        # These inserts are beyond the chart horizon and arrive out of time order.
        for index in range(70):
            db.add(Occurrence(
                source_session_id=1, source_sample=200000 + index,
                occurred_at=NOW - timedelta(days=50, seconds=index),
                form="Tusk", normalized_form="tusk", quote="Uzupełnienie historii", confidence=0.9,
            ))
        for index in range(100):
            db.add(Occurrence(
                source_session_id=1, source_sample=300000 + index,
                occurred_at=NOW + timedelta(days=1), form="Tusk", normalized_form="tusk",
                quote="Przyszła data", confidence=0.9,
            ))
    backfilled = build_snapshot(config, old_record, NOW)
    record = json.loads(backfilled.stats[1])["hourlyRecord"]
    assert record["count"] == 70
    assert len(backfilled.record_items) == 70
    assert publication_signature(edited) != publication_signature(backfilled)
    assert all(item.quote == "Uzupełnienie historii" for item in backfilled.record_items)
