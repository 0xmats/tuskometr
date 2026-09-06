import asyncio
from datetime import timedelta

from sqlalchemy import func, select
from test_dvr import NOW, RATE, FakeSource, Transcriber, run_windows
from test_dvr import environment as _environment_fixture

from app.dvr import utc
from app.dvr_runner import DvrRunner
from app.history import HistoricalBackfill, coverage, uncovered_ranges
from app.models import DvrProgress, Occurrence, PipelineState, SourceSession, TranscriptSegment
from app.transcriber import TranscriptionResult
from app.worker import TuskometrWorker

environment = _environment_fixture


def test_gap_detection_merges_overlap_and_includes_empty_history():
    end = NOW + timedelta(seconds=100)
    assert uncovered_ranges(NOW, end, []) == [(NOW, end)]
    covered = [
        (NOW + timedelta(seconds=60), NOW + timedelta(seconds=110)),
        (NOW - timedelta(seconds=10), NOW + timedelta(seconds=10)),
        (NOW + timedelta(seconds=5), NOW + timedelta(seconds=30)),
    ]
    assert uncovered_ranges(NOW, end, covered) == [
        (NOW + timedelta(seconds=30), NOW + timedelta(seconds=60)),
    ]


def prepare_history(environment):
    settings, factory = environment
    run_windows(settings, factory)
    settings.youtube_history_enabled = True
    with factory() as db:
        progress = db.scalar(select(DvrProgress))
    worker = TuskometrWorker(settings, Transcriber())
    return worker, factory, progress, FakeSource(settings)


def test_history_fills_all_old_ranges_and_preserves_live_state(environment):
    worker, factory, progress, source = prepare_history(environment)
    origin = utc(progress.time_origin)
    with factory() as db:
        before_state = db.get(PipelineState, 1).last_transcript_at
        before_progress = (progress.next_sample, progress.next_sequence)
    worker.transcriber.transcribe_pcm = lambda pcm: TranscriptionResult("", [], 0)

    async def exercise():
        # Recreate the historical scanner to simulate a restart after every window.
        for _ in range(3):
            await HistoricalBackfill(worker, factory).run_one(source, progress, await source.head())

    asyncio.run(exercise())
    with factory() as db:
        after = db.get(DvrProgress, progress.id)
        assert (after.next_sample, after.next_sequence) == before_progress
        assert db.get(PipelineState, 1).last_transcript_at == before_state
        assert (
            uncovered_ranges(
                origin,
                origin + timedelta(seconds=495),
                coverage(db, progress.source_url, origin, origin + timedelta(seconds=495)),
            )
            == []
        )
        assert db.scalar(select(func.count()).select_from(TranscriptSegment)) == 3
        # Silence/transcripts with no mentions still count as covered history.
        assert db.scalar(select(func.count()).select_from(Occurrence)) == 1


def test_history_failure_leaves_gap_for_retry_without_changing_live_progress(environment):
    worker, factory, progress, source = prepare_history(environment)

    def fail(pcm):
        raise RuntimeError("ASR unavailable")

    worker.transcriber.transcribe_pcm = fail
    scanner = HistoricalBackfill(worker, factory)
    asyncio.run(scanner.run_one(source, progress, asyncio.run(source.head())))
    assert scanner.next_scan > 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TranscriptSegment)) == 1
        assert db.get(DvrProgress, progress.id).next_sample == progress.next_sample
    worker.transcriber = Transcriber()
    asyncio.run(
        HistoricalBackfill(worker, factory).run_one(
            source,
            progress,
            asyncio.run(source.head()),
        )
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TranscriptSegment)) == 2


def test_history_excludes_mentions_already_covered_by_legacy_session(environment):
    from app.detection import WordToken

    worker, factory, progress, source = prepare_history(environment)
    origin = utc(progress.time_origin)
    with factory.begin() as db:
        legacy = SourceSession(
            source_type="youtube", source_url=progress.source_url, started_at=origin, status="ended"
        )
        db.add(legacy)
        db.flush()
        db.add(
            TranscriptSegment(
                source_session_id=legacy.id,
                started_at=origin + timedelta(seconds=10),
                ended_at=origin + timedelta(seconds=20),
                start_sample=0,
                end_sample=10 * RATE,
                text="Tusk",
                average_confidence=1,
                checksum="test",
                expires_at=NOW + timedelta(days=1),
            )
        )
        db.add(
            Occurrence(
                source_session_id=legacy.id,
                source_sample=1,
                occurred_at=origin + timedelta(seconds=15),
                form="Tusk",
                normalized_form="tusk",
                quote="Tusk",
                confidence=1,
            )
        )
    worker.transcriber.transcribe_pcm = lambda pcm: TranscriptionResult(
        "Tusk Tusk",
        [WordToken("Tusk", 5, 5.3, 1), WordToken("Tusk", 15, 15.3, 1)],
        1,
    )
    asyncio.run(
        worker._process_window(
            progress.source_session_id, b"\0\0" * (25 * RATE), 0, origin, historical=True
        )
    )
    with factory() as db:
        mentions = list(db.scalars(select(Occurrence).where(Occurrence.occurred_at < NOW)))
        assert len(mentions) == 3  # old live mention, legacy mention, new gap mention
        assert (
            sum(utc(item.occurred_at) == origin + timedelta(seconds=15) for item in mentions) == 1
        )


def test_other_sources_do_not_cover_this_stream(environment):
    worker, factory, progress, source = prepare_history(environment)
    with factory() as db:
        assert coverage(db, "https://other.test", NOW - timedelta(hours=12), NOW) == []


def test_history_yields_to_live_catchup(environment, monkeypatch):
    worker, factory, progress, source = prepare_history(environment)
    monkeypatch.setattr(FakeSource, "head_sequence", 200)
    requests_before = len(FakeSource.requested)
    asyncio.run(
        HistoricalBackfill(worker, factory).run_one(
            source,
            progress,
            asyncio.run(source.head()),
        )
    )
    assert len(FakeSource.requested) == requests_before


def test_live_loop_schedules_history_after_committing_live_window(environment, monkeypatch):
    settings, factory = environment
    settings.youtube_history_enabled = True
    worker = TuskometrWorker(settings, Transcriber())
    seen = []

    async def historical(self, source, progress, head):
        with factory() as db:
            seen.append(db.scalar(select(func.count()).select_from(TranscriptSegment)))
        worker.stop()

    monkeypatch.setattr(HistoricalBackfill, "run_one", historical)
    asyncio.run(DvrRunner(worker, factory).run())
    assert seen == [1]
