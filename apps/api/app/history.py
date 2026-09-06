"""Fill uncovered source-time ranges without rewinding the live DVR checkpoint."""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from .dvr import AudioFragment, Head, YoutubeDvrSource, utc
from .models import DvrProgress, SourceSession, TranscriptSegment
from .source import SourceError

if TYPE_CHECKING:
    from .worker import TuskometrWorker

logger = logging.getLogger("tuskometr.history")


def uncovered_ranges(start: datetime, end: datetime, covered) -> list[tuple[datetime, datetime]]:
    cursor = utc(start)
    end = utc(end)
    gaps = []
    for left, right in sorted((utc(a), utc(b)) for a, b in covered):
        if right <= cursor or left >= end:
            continue
        if left > cursor:
            gaps.append((cursor, min(left, end)))
        cursor = max(cursor, right)
        if cursor >= end:
            break
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


def coverage(db, source_url: str, start: datetime, end: datetime):
    return db.execute(
        select(TranscriptSegment.started_at, TranscriptSegment.ended_at)
        .join(SourceSession)
        .where(
            SourceSession.source_url == source_url,
            TranscriptSegment.ended_at > start,
            TranscriptSegment.started_at < end,
        )
    ).all()


class HistoricalBackfill:
    def __init__(self, worker: TuskometrWorker, factory):
        self.worker = worker
        self.settings = worker.settings
        self.factory = factory
        self.next_scan = 0.0
        self.earliest: AudioFragment | None = None

    async def run_one(self, source: YoutubeDvrSource, progress: DvrProgress, head: Head) -> None:
        if not self.settings.youtube_history_enabled or time.monotonic() < self.next_scan:
            return
        rate = self.settings.sample_rate
        if progress.next_sample is None or head.position - progress.next_sample / rate > (
            self.settings.chunk_seconds
        ):
            return  # Recover current ingestion before spending time on older gaps.
        try:
            sequence = source.earliest_sequence(head)
            if self.earliest is None or self.earliest.sequence != sequence:
                self.earliest = await source.fragment(sequence)
            origin = utc(progress.time_origin)
            lower = origin + timedelta(seconds=self.earliest.start_sample / rate)
            upper = origin + timedelta(seconds=min(head.position, progress.next_sample / rate))
            with self.factory() as db:
                gaps = uncovered_ranges(
                    lower, upper, coverage(db, progress.source_url, lower, upper)
                )
            # Ignore sub-sample rounding differences between timestamp representations.
            gaps = [(a, b) for a, b in gaps if (b - a).total_seconds() >= 1 / rate]
            if not gaps:
                self.next_scan = time.monotonic() + 60
                logger.info("Historia DVR: brak luk w dostępnym oknie")
                return
            left, right = gaps[0]
            overlap = self.settings.chunk_seconds - self.settings.chunk_step_seconds
            start = max(
                self.earliest.start_sample,
                round((left - origin).total_seconds() * rate) - overlap * rate,
            )
            # Include context on both sides, but only add mentions in uncovered ranges.
            end = min(
                round((right - origin).total_seconds() * rate) + overlap * rate,
                start
                + max(self.settings.chunk_seconds, self.settings.youtube_dvr_catchup_chunk_seconds)
                * rate,
                round(head.position * rate),
            )
            logger.info(
                "Historia DVR: uzupełnianie %s — %s; wykryte luki=%d",
                left.isoformat(),
                right.isoformat(),
                len(gaps),
            )
            pcm = await self.read_window(source, head, start, end)
            if self.worker.stop_event.is_set():
                return
            await self.worker._process_window(
                progress.source_session_id,
                pcm,
                start,
                origin,
                historical=True,
            )
        except Exception:
            # Historical failures must not reset/stop the working live reader.
            self.next_scan = time.monotonic() + 60
            logger.exception("Historia DVR: błąd uzupełniania; ponowienie za 60s")

    async def read_window(
        self,
        source: YoutubeDvrSource,
        head: Head,
        start: int,
        end: int,
    ) -> bytes:
        rate = self.settings.sample_rate
        if end <= start:
            raise SourceError("Pusty zakres historyczny")
        earliest = source.earliest_sequence(head)
        sequence = max(
            earliest,
            head.sequence
            - math.ceil(
                (head.position - start / rate) / source.fragment_seconds,
            )
            - 1,
        )
        # Sequence duration is approximate. Locate the fragment by its actual PTS.
        fragment = await source.fragment(sequence)
        for _ in range(20):
            if fragment.start_sample <= start < fragment.end_sample:
                break
            sequence += -1 if fragment.start_sample > start else 1
            if sequence < earliest or sequence > head.sequence:
                raise SourceError("Zakres historyczny nie jest już dostępny w DVR")
            fragment = await source.fragment(sequence)
        else:
            raise SourceError("Nie udało się odnaleźć pozycji historycznej DVR")
        buffer = bytearray(fragment.pcm)
        first_sample = fragment.start_sample
        while first_sample + len(buffer) // 2 < end:
            if self.worker.stop_event.is_set():
                return b""
            sequence += 1
            if sequence > head.sequence:
                raise SourceError("Zakres historyczny wykracza poza pobrane okno DVR")
            following = await source.fragment(sequence)
            if abs(following.start_sample - fragment.end_sample) > 2:
                raise SourceError("Nieciągłe timestampy historycznego audio DVR")
            buffer.extend(following.pcm)
            fragment = following
        return bytes(buffer[(start - first_sample) * 2 : (end - first_sample) * 2])
