import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.detection import WordToken
from app.dvr import AudioFragment, Head, YoutubeDvrSource, utc
from app.dvr_runner import DvrRunner
from app.models import Base, DvrProgress, IngestionGap, Occurrence, TranscriptSegment
from app.source import SourceError
from app.transcriber import TranscriptionResult
from app.worker import TuskometrWorker

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
RATE = 8000


class Transcriber:
    model_name = "test"

    def transcribe_pcm(self, pcm):
        return TranscriptionResult("Tusk", [WordToken("Tusk", 1, 1.3, 0.95)], 0.95)


class FakeSource:
    broadcast_id = "video:video.41:140"
    fragment_seconds = 5
    head_sequence = 100
    requested = []
    closed = False

    def __init__(self, settings):
        self.settings = settings

    async def open(self):
        head = await self.head()
        return Head(head.sequence - 6, head.position - 30, head.observed_at - timedelta(seconds=30))

    async def head(self):
        return Head(
            self.head_sequence,
            self.head_sequence * 5,
            NOW + timedelta(seconds=(self.head_sequence - 100) * 5),
        )

    earliest_sequence = YoutubeDvrSource.earliest_sequence

    async def fragment(self, sequence):
        self.requested.append(sequence)
        return AudioFragment(sequence, sequence * 5 * RATE, b"\0\0" * (5 * RATE))

    async def close(self):
        self.closed = True


@pytest.fixture
def environment(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr("app.worker.SessionLocal", factory)
    monkeypatch.setattr("app.dvr_runner.YoutubeDvrSource", FakeSource)
    monkeypatch.setattr(FakeSource, "head_sequence", 100)
    monkeypatch.setattr(FakeSource, "requested", [])
    settings = Settings(_env_file=None, sample_rate=RATE)
    yield settings, factory
    engine.dispose()


def run_windows(settings, factory, count=1):
    worker = TuskometrWorker(settings, Transcriber())
    process = worker._process_window
    calls = []

    async def tracked(*args, **kwargs):
        await process(*args, **kwargs)
        calls.append(args[2])
        if len(calls) == count:
            worker.stop()

    worker._process_window = tracked
    asyncio.run(DvrRunner(worker, factory).run())
    return calls


def test_restart_resumes_overlap_with_same_source_timeline(environment, monkeypatch):
    settings, factory = environment
    first = run_windows(settings, factory)
    with factory() as db:
        before = db.scalar(select(DvrProgress))
        checkpoint = before.next_sample
        sequence = before.next_sequence
        origin = before.time_origin
        session_id = before.source_session_id
    monkeypatch.setattr(FakeSource, "head_sequence", 120)
    FakeSource.requested.clear()
    second = run_windows(settings, factory)
    assert second == [checkpoint]
    assert second[0] - first[0] == 20 * RATE
    assert FakeSource.requested[0] == sequence
    with factory() as db:
        after = db.scalar(select(DvrProgress))
        assert after.source_session_id == session_id
        assert after.time_origin == origin
        assert db.scalar(select(func.count()).select_from(IngestionGap)) == 0
        assert db.scalar(select(func.count()).select_from(TranscriptSegment)) == 2


def test_expired_window_records_gap_and_catches_up_from_oldest(environment, monkeypatch):
    settings, factory = environment
    run_windows(settings, factory)
    with factory() as db:
        row = db.scalar(select(DvrProgress))
        expected_start = utc(row.time_origin) + timedelta(seconds=row.next_sample / RATE)
    monkeypatch.setattr(FakeSource, "head_sequence", 9100)
    FakeSource.requested.clear()
    run_windows(settings, factory)
    assert FakeSource.requested[0] == 9100 - 8640 + 2
    with factory() as db:
        gap = db.scalar(select(IngestionGap))
        assert utc(gap.started_at) == expected_start
        assert utc(gap.ended_at) > expected_start
        assert gap.reason == "dvr_unavailable"


def test_encoder_restart_creates_new_session_and_records_unavailable_time(
    environment,
    monkeypatch,
):
    settings, factory = environment
    run_windows(settings, factory)
    with factory() as db:
        old_session = db.scalar(select(DvrProgress)).source_session_id
    monkeypatch.setattr(FakeSource, "broadcast_id", "video:video.42:140")
    monkeypatch.setattr(FakeSource, "head_sequence", 10)

    async def new_head(self):
        return Head(10, 50, NOW + timedelta(minutes=10))

    monkeypatch.setattr(FakeSource, "head", new_head)
    run_windows(settings, factory)
    with factory() as db:
        row = db.scalar(select(DvrProgress))
        assert row.source_session_id != old_session
        assert row.broadcast_id == "video:video.42:140"
        assert db.scalar(select(func.count()).select_from(IngestionGap)) == 1


def test_results_and_checkpoint_rollback_together(environment, monkeypatch):
    settings, factory = environment
    worker = TuskometrWorker(settings, Transcriber())
    store = worker._store_occurrences

    def fail_after_detections(*args):
        store(*args)
        raise RuntimeError("database failure")

    monkeypatch.setattr(worker, "_store_occurrences", fail_after_detections)
    with pytest.raises(RuntimeError, match="database failure"):
        asyncio.run(DvrRunner(worker, factory).run())
    with factory() as db:
        row = db.scalar(select(DvrProgress))
        expected = row.next_sample
        assert row.next_sequence == 95
        assert db.scalar(select(func.count()).select_from(TranscriptSegment)) == 0
        assert db.scalar(select(func.count()).select_from(Occurrence)) == 0
    assert run_windows(settings, factory) == [expected]


def test_transcription_failure_does_not_advance_checkpoint(environment, monkeypatch):
    settings, factory = environment
    transcriber = Transcriber()

    def fail(pcm):
        raise RuntimeError("API unavailable")

    monkeypatch.setattr(transcriber, "transcribe_pcm", fail)
    worker = TuskometrWorker(settings, transcriber)
    with pytest.raises(RuntimeError, match="API unavailable"):
        asyncio.run(DvrRunner(worker, factory).run())
    with factory() as db:
        row = db.scalar(select(DvrProgress))
        assert row.next_sample == 475 * RATE
        assert row.next_sequence == 95
        assert db.scalar(select(func.count()).select_from(TranscriptSegment)) == 0


def test_replaying_committed_window_does_not_duplicate_mentions(environment):
    settings, factory = environment
    calls = run_windows(settings, factory)
    with factory() as db:
        row = db.scalar(select(DvrProgress))
    worker = TuskometrWorker(settings, Transcriber())
    asyncio.run(
        worker._process_window(
            row.source_session_id,
            b"\0\0" * (25 * RATE),
            calls[0],
            utc(row.time_origin),
            dvr_checkpoint=(row.id, row.next_sequence, row.next_sample),
        )
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Occurrence)) == 1
        assert db.scalar(select(func.count()).select_from(TranscriptSegment)) == 1


@pytest.mark.parametrize("step", [2, 20, 25])
def test_window_steps_preserve_progress_without_dropping_audio(environment, monkeypatch, step):
    settings, factory = environment
    settings.chunk_step_seconds = step
    monkeypatch.setattr(FakeSource, "head_sequence", 200)
    # First resolve near 100, then expose enough data for three windows.
    monkeypatch.setattr(
        FakeSource, "open", AsyncMock(return_value=Head(94, 470, NOW - timedelta(seconds=30)))
    )
    calls = run_windows(settings, factory, count=3)
    assert calls == [475 * RATE, (475 + step) * RATE, (475 + 2 * step) * RATE]
    assert len(FakeSource.requested) <= 16


def test_failed_fragment_is_retried_without_skipping(environment, monkeypatch):
    settings, factory = environment

    async def fail(self, sequence):
        raise SourceError("expired URL")

    monkeypatch.setattr(FakeSource, "fragment", fail)
    worker = TuskometrWorker(settings, Transcriber())
    with pytest.raises(SourceError):
        asyncio.run(DvrRunner(worker, factory).run())
    with factory() as db:
        row = db.scalar(select(DvrProgress))
        assert row.next_sequence == 95
        assert row.next_sample is None
        assert db.scalar(select(func.count()).select_from(IngestionGap)) == 0


def test_http_error_does_not_expose_signed_url():
    async def exercise():
        source = YoutubeDvrSource(Settings(_env_file=None))
        await source.client.aclose()
        source.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403),
            )
        )
        source.url = "https://example.test/audio?secret=token"
        try:
            with pytest.raises(SourceError, match="segmentu DVR 42") as error:
                await source.fragment(42)
            assert "token" not in str(error.value)
        finally:
            await source.close()

    asyncio.run(exercise())


def test_wrong_sequence_response_is_rejected():
    async def exercise():
        source = YoutubeDvrSource(Settings(_env_file=None))
        await source.client.aclose()
        source.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, headers={"x-sequence-num": "99"}, content=b"x"),
            )
        )
        source.url = "https://example.test/audio"
        try:
            with pytest.raises(SourceError, match="inny segment"):
                await source.fragment(42)
        finally:
            await source.close()

    asyncio.run(exercise())


def test_overlapping_windows_count_same_word_once(environment):
    settings, factory = environment
    calls = run_windows(settings, factory)
    with factory() as db:
        row = db.scalar(select(DvrProgress))
    worker = TuskometrWorker(settings, Transcriber())

    # The word is at +1s in the committed window and +21s in the preceding window.
    class OverlapTranscriber:
        model_name = "test"

        def transcribe_pcm(self, pcm):
            return TranscriptionResult("Tusk", [WordToken("Tusk", 21, 21.3, 0.95)], 0.95)

    worker.transcriber = OverlapTranscriber()
    asyncio.run(
        worker._process_window(
            row.source_session_id,
            b"\0\0" * (25 * RATE),
            calls[0] - 20 * RATE,
            utc(row.time_origin),
        )
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Occurrence)) == 1


def test_first_activation_starts_after_head_without_replaying_legacy_audio(environment):
    settings, factory = environment
    runner = DvrRunner(TuskometrWorker(settings, Transcriber()), factory)
    row = runner.prepare(FakeSource(settings), Head(100, 500, NOW))
    assert row.next_sequence == 101
    assert row.next_sample is None


def test_frozen_head_triggers_source_refresh(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.dvr.time.monotonic", lambda: clock[0])

    async def exercise():
        source = YoutubeDvrSource(Settings(_env_file=None))
        await source.client.aclose()
        source.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={
                        "x-head-seqnum": "100",
                        "x-head-time-millis": "500000",
                        "x-walltime-ms": str(int(NOW.timestamp() * 1000)),
                    },
                ),
            )
        )
        source.url = "https://example.test/audio"
        try:
            assert (await source.head(force=True)).sequence == 100
            clock[0] += 61
            with pytest.raises(SourceError, match="60 sekund"):
                await source.head(force=True)
        finally:
            await source.close()

    asyncio.run(exercise())
