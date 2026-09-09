import json
from dataclasses import replace

import pytest
from test_publisher import database  # noqa: F401
from test_r2_publisher import Store

from app.config import Settings
from app.publisher import PublicationSchedule, publish
from app.r2_publisher import R2Publisher
from app.snapshot import build_snapshot
from app.youtube_timeline import (
    browser_proxy,
    calibrate_once,
    read_calibration,
    valid_calibration,
    video_id,
    write_calibration,
)

VIDEO = "dzntyCTgJMQ"
NOW = 1_800_000_000.0


def sample(now=NOW):
    return {"videoId": VIDEO, "origin": now - 100_000, "checkedAt": now, "expiresAt": now + 180}


def config(tmp_path):
    return Settings(_env_file=None, youtube_timeline_file=tmp_path / "youtube.json",
                    dashboard_output_dir=tmp_path / "dashboard", r2_bucket="test",
                    r2_endpoint_url="https://example.com")


def test_read_valid_fresh_result_and_expire_without_another_write(tmp_path):
    settings = config(tmp_path)
    assert read_calibration(settings, NOW) is None
    write_calibration(settings.youtube_timeline_file, sample())
    assert read_calibration(settings, NOW) == sample()
    assert read_calibration(settings, NOW + 179) == sample()
    assert read_calibration(settings, NOW + 180) is None
    assert read_calibration(settings, NOW - 1) is None


@pytest.mark.parametrize("field,value", [
    ("videoId", "other-video"), ("origin", None), ("origin", float("nan")),
    ("origin", float("inf")), ("origin", "1000"), ("origin", True),
    ("origin", -100), ("origin", NOW), ("checkedAt", NOW + 1),
    ("expiresAt", NOW), ("expiresAt", NOW + 301), ("checkedAt", None),
])
def test_reject_invalid_or_wrong_source(field, value):
    assert not valid_calibration({**sample(), field: value}, VIDEO, NOW)


def test_corrupt_file_or_changed_source_cannot_break_publishing(tmp_path):
    settings = config(tmp_path)
    settings.youtube_timeline_file.write_text("{partial")
    assert read_calibration(settings, NOW) is None
    write_calibration(settings.youtube_timeline_file, sample())
    settings.source_url = "https://youtube.com/watch?v=abcdefghijk"
    assert read_calibration(settings, NOW) is None
    settings.source_url = "not a youtube url"
    assert read_calibration(settings, NOW) is None


def test_failed_measurement_keeps_last_good_until_expiry(tmp_path, monkeypatch):
    settings = config(tmp_path)
    write_calibration(settings.youtube_timeline_file, sample())

    def fail(_):
        raise RuntimeError("unavailable")

    monkeypatch.setattr("app.youtube_timeline.measure", fail)
    with pytest.raises(RuntimeError):
        calibrate_once(settings)
    assert read_calibration(settings, NOW + 100) == sample()
    assert read_calibration(settings, NOW + 180) is None
    monkeypatch.setattr("app.youtube_timeline.measure", lambda _: sample(NOW + 200))
    calibrate_once(settings)
    assert read_calibration(settings, NOW + 200) == sample(NOW + 200)


def test_source_url_and_proxy_credentials():
    assert video_id(f"https://www.youtube.com/watch?v={VIDEO}") == VIDEO
    assert video_id(f"https://youtu.be/{VIDEO}") == VIDEO
    with pytest.raises(ValueError):
        video_id(f"https://example.com/watch?v={VIDEO}")
    assert browser_proxy("") is None
    assert browser_proxy("http://user:p%40ss@localhost:18888") == {
        "server": "http://localhost:18888", "username": "user", "password": "p@ss",
    }


@pytest.mark.parametrize("remote", [False, True])
def test_manifest_publishes_and_expires_timeline_promptly(database, tmp_path, monkeypatch, remote):  # noqa: F811
    settings = config(tmp_path)
    initial = build_snapshot(settings, database[0])
    now = initial.generated_at.timestamp()
    write_calibration(settings.youtube_timeline_file, sample(now))
    snapshot = build_snapshot(settings, database[0], initial.generated_at)
    assert snapshot.youtube_timeline == sample(now)
    store = Store()
    writer = R2Publisher(settings, store).publish if remote else (
        lambda value: publish(value, settings.dashboard_output_dir)
    )
    schedule = PublicationSchedule(settings)
    monkeypatch.setattr("app.publisher.time.monotonic", lambda: 0)
    first = schedule.publish_if_due(snapshot, writer)
    assert first["youtubeTimeline"] == sample(now)
    assert schedule.publish_if_due(snapshot, writer) is None
    # Calibration changes trigger publication even with identical mentions/status.
    changed = replace(snapshot, youtube_timeline=sample(now + 1))
    second = schedule.publish_if_due(changed, writer)
    assert second["youtubeTimeline"] == sample(now + 1)
    expired = schedule.publish_if_due(replace(changed, youtube_timeline=None), writer)
    assert expired["youtubeTimeline"] is None
    body = (store.objects["dashboard/manifest.json"]["Body"] if remote else
            (settings.dashboard_output_dir / "manifest.json").read_bytes())
    assert json.loads(body)["youtubeTimeline"] is None
