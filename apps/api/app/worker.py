from __future__ import annotations

import asyncio
import hashlib
import logging
import signal
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import SessionLocal, init_db
from .detection import (
    DetectedOccurrence,
    find_candidates,
    materialize_occurrence,
)
from .models import DvrProgress, Occurrence, PipelineState, SourceSession, TranscriptSegment
from .monitoring import Heartbeat
from .source import ProcessAudioSource, SourceError, validate_source
from .transcriber import Transcriber, TranscriptionResult, WhisperTranscriber, create_transcriber

logger = logging.getLogger("tuskometr.worker")
UTC = UTC


class TuskometrWorker:
    def __init__(
        self,
        settings: Settings,
        transcriber: Transcriber | None = None,
    ) -> None:
        self.settings = settings
        self.heartbeat = Heartbeat(
            settings.healthchecks_collecting_url.get_secret_value(), "collecting"
        )
        self.transcriber = transcriber
        self.stop_event = asyncio.Event()
        self.reconnect_count = 0
        self.slow_window_streak = 0
        self.fallback_active = False

    async def run_forever(self) -> None:
        init_db()
        validate_source(self.settings)
        model_name = (
            self.settings.asr_api_model
            if self.settings.asr_provider == "ovh"
            else self.settings.asr_model
        )
        self._update_state("starting", model_name=model_name)
        if self.transcriber is None:
            logger.info("Transkrypcja %s: %s", self.settings.asr_provider, model_name)
            self.transcriber = await asyncio.to_thread(create_transcriber, self.settings)
        self._update_state("starting", model_name=self.transcriber.model_name)

        retry_delays = (5, 15, 30, 60)
        attempt = 0
        while not self.stop_event.is_set():
            try:
                if self.settings.source_mode == "youtube" and self.settings.youtube_dvr_enabled:
                    from .dvr_runner import DvrRunner

                    await DvrRunner(self, SessionLocal).run()
                else:
                    await self._run_source_session()
                if not self.stop_event.is_set():
                    raise SourceError("Transmisja zakończyła się bez sygnału końca pracy")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.reconnect_count += 1
                delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                attempt += 1
                message = str(error) or error.__class__.__name__
                logger.exception("Błąd źródła; ponowienie za %ss: %s", delay, message)
                self._update_state(
                    "reconnecting",
                    last_error=message[-1000:],
                    reconnect_count=self.reconnect_count,
                )
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
                except TimeoutError:
                    pass
            else:
                attempt = 0
        self._update_state("offline", last_error=None)

    async def _run_source_session(self) -> None:
        source = ProcessAudioSource(self.settings)
        started_at = datetime.now(UTC)
        source_session_id = self._create_source_session(started_at)
        producer: asyncio.Task | None = None
        try:
            await source.open()
            self._mark_session(source_session_id, "live")
            self._update_state("live", last_error=None)

            bytes_per_second = self.settings.sample_rate * 2
            window_bytes = self.settings.chunk_seconds * bytes_per_second
            step_bytes = self.settings.chunk_step_seconds * bytes_per_second
            queue_chunks = max(4, self.settings.max_audio_queue_seconds // 2)
            queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=queue_chunks)
            producer = asyncio.create_task(self._capture(source, queue))
            buffer = bytearray()
            start_sample = 0
            first_audio_at: datetime | None = None

            while not self.stop_event.is_set():
                while len(buffer) < window_bytes:
                    item = await queue.get()
                    if item is None:
                        break
                    if first_audio_at is None:
                        first_audio_at = datetime.now(UTC)
                        self._set_session_started_at(source_session_id, first_audio_at)
                    buffer.extend(item)
                if len(buffer) < window_bytes:
                    if len(buffer) >= 5 * bytes_per_second and first_audio_at is not None:
                        await self._process_window(
                            source_session_id,
                            bytes(buffer),
                            start_sample,
                            first_audio_at,
                        )
                    break
                if first_audio_at is None:
                    first_audio_at = datetime.now(UTC)
                await self._process_window(
                    source_session_id,
                    bytes(buffer[:window_bytes]),
                    start_sample,
                    first_audio_at,
                )
                del buffer[:step_bytes]
                start_sample += step_bytes // 2

            if producer:
                await producer
            return_code = await source.wait()
            if not self.stop_event.is_set():
                raise SourceError(f"FFmpeg zakończył pracę z kodem {return_code}")
        except Exception as error:
            self._mark_session(source_session_id, "error", str(error)[-1000:])
            raise
        finally:
            if producer and not producer.done():
                producer.cancel()
                with suppress(asyncio.CancelledError):
                    await producer
            await source.close()
            self._finish_session(source_session_id)

    async def _capture(
        self, source: ProcessAudioSource, queue: asyncio.Queue[bytes | None]
    ) -> None:
        try:
            while not self.stop_event.is_set():
                data = await source.read()
                if not data:
                    break
                await queue.put(data)
                self._touch_audio()
        finally:
            await queue.put(None)

    async def _process_window(
        self,
        source_session_id: int,
        pcm: bytes,
        start_sample: int,
        session_started_at: datetime,
        dvr_checkpoint: tuple[int, int, int] | None = None,
    ) -> None:
        assert self.transcriber is not None
        chunk_started_at = session_started_at + timedelta(
            seconds=start_sample / self.settings.sample_rate
        )
        started = datetime.now(UTC)
        result = await asyncio.to_thread(self.transcriber.transcribe_pcm, pcm)
        duration_seconds = len(pcm) / 2 / self.settings.sample_rate
        chunk_finished_at = chunk_started_at + timedelta(seconds=duration_seconds)
        lag = max(0.0, (datetime.now(UTC) - chunk_finished_at).total_seconds())

        detections: list[DetectedOccurrence] = []
        for candidate in find_candidates(result.words):
            verified_confidence: float | None = None
            if not candidate.exact:
                verification = await asyncio.to_thread(
                    self.transcriber.verify_fuzzy_candidate,
                    pcm,
                    candidate.token.start,
                    candidate.token.end,
                )
                if verification is None:
                    continue
                verified_form, verified_confidence = verification
                if verified_form != candidate.normalized_form:
                    continue
            detections.append(
                materialize_occurrence(
                    candidate=candidate,
                    words=result.words,
                    chunk_started_at=chunk_started_at,
                    chunk_start_sample=start_sample,
                    sample_rate=self.settings.sample_rate,
                    verified_confidence=verified_confidence,
                )
            )
        # Results and the next DVR position must commit together. A crash or
        # verification/DB failure leaves the same window available for replay.
        with SessionLocal.begin() as db:
            segment_id = self._store_segment(
                db=db,
                source_session_id=source_session_id,
                start_sample=start_sample,
                pcm=pcm,
                chunk_started_at=chunk_started_at,
                result=result,
            )
            self._store_occurrences(db, source_session_id, segment_id, detections)
            if dvr_checkpoint is not None:
                progress_id, next_sequence, next_sample = dvr_checkpoint
                progress = db.get(DvrProgress, progress_id)
                if progress is None:
                    raise RuntimeError("Brak checkpointu DVR")
                progress.next_sequence = next_sequence
                progress.next_sample = next_sample
        self._update_state(
            "live",
            last_transcript_at=datetime.now(UTC),
            lag_seconds=lag,
            last_error=None,
        )
        elapsed = (datetime.now(UTC) - started).total_seconds()
        if elapsed / duration_seconds > 0.8:
            self.slow_window_streak += 1
        else:
            self.slow_window_streak = 0
        if (
            self.settings.asr_provider == "local"
            and self.slow_window_streak >= 3
            and not self.fallback_active
            and self.settings.asr_fallback_model != self.transcriber.model_name
        ):
            await self._activate_fallback_model()
        logger.info(
            "Segment %.1fs przetworzony w %.2fs, tekst=%d, trafienia=%d, lag=%.1fs",
            duration_seconds,
            elapsed,
            len(result.text),
            len(detections),
            lag,
        )
        self._cleanup_expired()
        await asyncio.to_thread(self.heartbeat.ping)

    async def _activate_fallback_model(self) -> None:
        logger.warning(
            "Model %s nie nadąża przez trzy okna; przełączanie na %s",
            self.transcriber.model_name if self.transcriber else "unknown",
            self.settings.asr_fallback_model,
        )
        replacement = await asyncio.to_thread(
            WhisperTranscriber,
            self.settings,
            self.settings.asr_fallback_model,
        )
        self.transcriber = replacement
        self.fallback_active = True
        self.slow_window_streak = 0
        self._update_state("live", model_name=replacement.model_name)

    def _create_source_session(self, started_at: datetime) -> int:
        with SessionLocal() as db:
            row = SourceSession(
                source_type=self.settings.source_mode,
                source_url=self.settings.source_url,
                started_at=started_at,
                status="starting",
            )
            db.add(row)
            db.commit()
            return row.id

    @staticmethod
    def _set_session_started_at(source_session_id: int, started_at: datetime) -> None:
        with SessionLocal() as db:
            row = db.get(SourceSession, source_session_id)
            if row:
                row.started_at = started_at
                db.commit()

    @staticmethod
    def _mark_session(source_session_id: int, status: str, error: str | None = None) -> None:
        with SessionLocal() as db:
            row = db.get(SourceSession, source_session_id)
            if row:
                row.status = status
                row.last_error = error
                db.commit()

    @staticmethod
    def _finish_session(source_session_id: int) -> None:
        with SessionLocal() as db:
            row = db.get(SourceSession, source_session_id)
            if row:
                row.ended_at = datetime.now(UTC)
                if row.status != "error":
                    row.status = "ended"
                db.commit()

    def _store_segment(
        self,
        db: Session,
        source_session_id: int,
        start_sample: int,
        pcm: bytes,
        chunk_started_at: datetime,
        result: TranscriptionResult,
    ) -> int:
        end_sample = start_sample + len(pcm) // 2
        duration = len(pcm) / 2 / self.settings.sample_rate
        expires_at = datetime.now(UTC) + timedelta(days=self.settings.transcript_retention_days)
        checksum = hashlib.sha256(result.text.encode()).hexdigest()
        existing = db.scalar(
            select(TranscriptSegment).where(
                TranscriptSegment.source_session_id == source_session_id,
                TranscriptSegment.start_sample == start_sample,
                TranscriptSegment.end_sample == end_sample,
            )
        )
        if existing:
            return existing.id
        row = TranscriptSegment(
            source_session_id=source_session_id,
            started_at=chunk_started_at,
            ended_at=chunk_started_at + timedelta(seconds=duration),
            start_sample=start_sample,
            end_sample=end_sample,
            text=result.text,
            average_confidence=result.average_confidence,
            checksum=checksum,
            expires_at=expires_at,
        )
        db.add(row)
        db.flush()
        return row.id

    def _store_occurrences(
        self,
        db: Session,
        source_session_id: int,
        segment_id: int,
        detections: list[DetectedOccurrence],
    ) -> None:
        tolerance_samples = round(self.settings.sample_rate * 0.75)
        for detection in detections:
            duplicate = db.scalar(
                select(Occurrence.id).where(
                    Occurrence.source_session_id == source_session_id,
                    Occurrence.normalized_form == detection.normalized_form,
                    Occurrence.source_sample.between(
                        detection.source_sample - tolerance_samples,
                        detection.source_sample + tolerance_samples,
                    ),
                )
            )
            if duplicate:
                continue
            db.add(
                Occurrence(
                    source_session_id=source_session_id,
                    segment_id=segment_id,
                    occurred_at=detection.occurred_at,
                    source_sample=detection.source_sample,
                    form=detection.form,
                    normalized_form=detection.normalized_form,
                    quote=detection.quote,
                    confidence=detection.confidence,
                    source_position_seconds=detection.source_position_seconds,
                )
            )
            db.flush()

    def _touch_audio(self) -> None:
        self._update_state("live", last_audio_at=datetime.now(UTC), last_error=None)

    def _update_state(self, state_name: str, **values) -> None:
        with SessionLocal() as db:
            row = db.get(PipelineState, 1)
            if row is None:
                row = PipelineState(id=1)
                db.add(row)
            row.state = state_name
            row.updated_at = datetime.now(UTC)
            for key, value in values.items():
                setattr(row, key, value)
            db.commit()

    @staticmethod
    def _cleanup_expired() -> None:
        with SessionLocal() as db:
            db.execute(
                delete(TranscriptSegment).where(TranscriptSegment.expires_at < datetime.now(UTC))
            )
            db.commit()

    def stop(self) -> None:
        self.stop_event.set()


async def async_main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = TuskometrWorker(get_settings())
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, worker.stop)
    await worker.run_forever()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
