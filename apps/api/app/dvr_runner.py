from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from .dvr import AudioFragment, Head, YoutubeDvrSource, time_origin, utc
from .models import DvrProgress, IngestionGap, SourceSession
from .source import SourceError

if TYPE_CHECKING:
    from .worker import TuskometrWorker

logger = logging.getLogger("tuskometr.dvr")


class DvrRunner:
    def __init__(self, worker: TuskometrWorker, factory):
        self.worker = worker
        self.settings = worker.settings
        self.factory = factory

    def prepare(self, source: YoutubeDvrSource, head: Head) -> DvrProgress:
        with self.factory() as db:
            row = db.scalar(
                select(DvrProgress).where(
                    DvrProgress.source_url == self.settings.source_url,
                )
            )
            if row and row.broadcast_id == source.broadcast_id:
                if row.sample_rate != self.settings.sample_rate:
                    raise SourceError("DVR: SAMPLE_RATE musi pozostać zgodny z zapisanym postępem")
                return row
            origin = time_origin(head)
            next_sample = None
            # First activation has no trustworthy source checkpoint. Begin with
            # the next fragment rather than replaying the legacy worker's tail.
            sequence = head.sequence + 1
            if row:
                old_session = db.get(SourceSession, row.source_session_id)
                old_session.status = "ended"
                old_session.ended_at = datetime.now(UTC)
                if row.next_sample is not None:
                    next_at = utc(row.time_origin) + timedelta(
                        seconds=row.next_sample / row.sample_rate,
                    )
                    next_sample = round(
                        (next_at - origin).total_seconds() * self.settings.sample_rate
                    )
                    sequence = max(
                        source.earliest_sequence(head),
                        min(
                            head.sequence,
                            head.sequence
                            - math.ceil(
                                (head.position - next_sample / self.settings.sample_rate)
                                / source.fragment_seconds,
                            )
                            - 1,
                        ),
                    )
            session = SourceSession(
                source_type="youtube",
                source_url=self.settings.source_url,
                started_at=origin,
                status="starting",
            )
            db.add(session)
            db.flush()
            if row is None:
                row = DvrProgress(source_url=self.settings.source_url)
                db.add(row)
            row.broadcast_id = source.broadcast_id
            row.source_session_id = session.id
            row.time_origin = origin
            row.sample_rate = self.settings.sample_rate
            row.next_sequence = sequence
            row.next_sample = next_sample
            db.commit()
            return row

    def align(self, progress: DvrProgress, first: AudioFragment) -> DvrProgress:
        """Initialize a position, or durably record an expired/discontinuous interval."""
        with self.factory() as db:
            row = db.get(DvrProgress, progress.id)
            if row.next_sample is not None and first.start_sample > row.next_sample + 2:
                start = utc(row.time_origin) + timedelta(seconds=row.next_sample / row.sample_rate)
                end = utc(row.time_origin) + timedelta(seconds=first.start_sample / row.sample_rate)
                db.add(
                    IngestionGap(
                        source_url=row.source_url,
                        started_at=start,
                        ended_at=end,
                        reason="dvr_unavailable",
                    )
                )
                logger.warning("Nieodzyskiwalna luka DVR: %s — %s", start, end)
            row.next_sample = first.start_sample
            row.next_sequence = first.sequence
            db.commit()
            return row

    async def run(self) -> None:
        source = YoutubeDvrSource(self.settings)
        progress = None
        try:
            head = await source.open()
            progress = self.prepare(source, head)
            self.worker._mark_session(progress.source_session_id, "live")
            self.worker._update_state("live", last_error=None)
            logger.info(
                "DVR: wznawianie od segmentu %d; bieżący segment %d",
                progress.next_sequence,
                head.sequence,
            )
            fragments: list[AudioFragment] = []
            rate = self.settings.sample_rate
            window_samples = self.settings.chunk_seconds * rate
            step_samples = self.settings.chunk_step_seconds * rate
            while not self.worker.stop_event.is_set():
                head = await source.head()
                earliest = source.earliest_sequence(head)
                sequence = fragments[-1].sequence + 1 if fragments else progress.next_sequence
                if progress.next_sequence < earliest:
                    fragments.clear()
                    sequence = earliest
                if sequence > head.sequence:
                    try:
                        await asyncio.wait_for(self.worker.stop_event.wait(), timeout=2)
                    except TimeoutError:
                        pass
                    continue
                fragment = await source.fragment(sequence)
                self.worker._touch_audio()
                if fragments:
                    # Resampling individual AAC fragments can round by one sample.
                    difference = fragment.start_sample - fragments[-1].end_sample
                    if abs(difference) > 2:
                        raise SourceError(
                            "Nieciągłe timestampy audio DVR; ponowienie od checkpointu",
                        )
                fragments.append(fragment)
                if progress.next_sample is None or (
                    len(fragments) == 1 and progress.next_sample < fragment.start_sample
                ):
                    progress = self.align(progress, fragment)
                # Bound memory even when a changed encoder timeline starts well
                # before the desired position.
                while len(fragments) > 1 and fragments[0].end_sample <= progress.next_sample:
                    fragments.pop(0)
                start = fragments[0].start_sample
                pcm = b"".join(item.pcm for item in fragments)
                offset = progress.next_sample - start
                if offset < 0:
                    raise SourceError("Nieprawidłowa pozycja wznowienia DVR")
                if len(pcm) // 2 - offset < window_samples:
                    continue
                while (
                    len(pcm) // 2 - offset >= window_samples and not self.worker.stop_event.is_set()
                ):
                    next_sample = progress.next_sample + step_samples
                    # With CHUNK_STEP_SECONDS == CHUNK_SECONDS the next window may
                    # begin exactly at the next, not-yet-downloaded source fragment.
                    next_sequence = fragments[-1].sequence + 1
                    for item in fragments:
                        if item.end_sample > next_sample:
                            next_sequence = item.sequence
                            break
                    await self.worker._process_window(
                        progress.source_session_id,
                        pcm[offset * 2 : (offset + window_samples) * 2],
                        progress.next_sample,
                        utc(progress.time_origin),
                        dvr_checkpoint=(progress.id, next_sequence, next_sample),
                    )
                    progress.next_sample = next_sample
                    progress.next_sequence = next_sequence
                    offset = progress.next_sample - start
                fragments = [item for item in fragments if item.sequence >= progress.next_sequence]
        except Exception as error:
            if progress:
                self.worker._mark_session(progress.source_session_id, "error", str(error)[-1000:])
            raise
        finally:
            await source.close()
            if progress and self.worker.stop_event.is_set():
                self.worker._mark_session(progress.source_session_id, "paused")
