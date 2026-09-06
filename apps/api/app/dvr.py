"""Bounded, on-demand YouTube DVR reads. Only progress is persisted, never audio."""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .config import Settings
from .source import SourceError, process_error


async def run_process(*command: str, data: bytes | None = None) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        try:
            output, stderr = await asyncio.wait_for(process.communicate(data), timeout=60)
        except TimeoutError:
            raise SourceError(f"{command[0]}: przekroczono czas odczytu DVR (60s)") from None
        if process.returncode:
            detail = process_error(stderr) or "brak szczegółów na stderr"
            raise SourceError(
                f"{command[0]}: błąd odczytu DVR (kod {process.returncode}): {detail}",
            )
        return output
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


@dataclass(frozen=True)
class Head:
    sequence: int
    position: float
    observed_at: datetime


@dataclass(frozen=True)
class AudioFragment:
    sequence: int
    start_sample: int
    pcm: bytes

    @property
    def end_sample(self) -> int:
        return self.start_sample + len(self.pcm) // 2


class YoutubeDvrSource:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=30, follow_redirects=True,
            proxy=settings.youtube_proxy_url.get_secret_value() or None,
        )
        self.url = ""
        self.broadcast_id = ""
        self.fragment_seconds = 5.0
        self._head: Head | None = None
        self._head_fetched = 0.0
        self._head_advanced = 0.0

    async def open(self) -> Head:
        # mweb does not expose the adaptive formats needed for sequence-based DVR.
        command = [
            "yt-dlp",
            "--ignore-config",
            "--no-plugin-dirs",
            "--no-playlist",
            "--js-runtimes",
            "deno",
            "--live-from-start",
            "--skip-download",
            "--dump-single-json",
            "--format",
            "140",
        ]
        if proxy := self.settings.youtube_proxy_url.get_secret_value():
            # Media requests must use the same egress as metadata.
            command.extend(["--proxy", proxy])
        command.append(self.settings.source_url)
        info = json.loads(await run_process(*command))
        if info.get("live_status") != "is_live":
            raise SourceError("Źródło DVR nie jest aktywną transmisją YouTube")
        self.url = info.get("url", "")
        self.fragment_seconds = float(info.get("target_duration", 0))
        query = dict(parse_qsl(urlsplit(self.url).query))
        stream_id = query.get("id")
        if not stream_id or not 0 < self.fragment_seconds <= 30:
            raise SourceError("Brak identyfikatora lub czasu segmentów DVR")
        self.broadcast_id = f"{info['id']}:{stream_id}:140"
        return await self.head(force=True)

    async def head(self, *, force: bool = False) -> Head:
        if not force and self._head and time.monotonic() - self._head_fetched < 2:
            return self._head
        try:
            response = await self.client.head(self.url)
            response.raise_for_status()
            headers = response.headers
            head = Head(
                sequence=int(headers["x-head-seqnum"]),
                position=float(headers["x-head-time-millis"]) / 1000,
                observed_at=datetime.fromtimestamp(float(headers["x-walltime-ms"]) / 1000, UTC),
            )
            now = time.monotonic()
            if self._head is None or head.sequence != self._head.sequence:
                self._head_advanced = now
            elif now - self._head_advanced > 60:
                # An old encoder URL can keep returning a frozen head with HTTP
                # 200 after the watch page has switched to a new generation.
                raise SourceError("DVR nie przesuwa się od 60 sekund; odświeżanie źródła")
            self._head = head
            self._head_fetched = now
            return self._head
        except (httpx.HTTPError, ValueError, KeyError):
            raise SourceError("Nie udało się odczytać pozycji transmisji DVR") from None

    def earliest_sequence(self, head: Head) -> int:
        # Leave two fragments of margin at the moving DVR boundary.
        return max(
            0,
            head.sequence
            - math.floor(
                self.settings.youtube_dvr_hours * 3600 / self.fragment_seconds,
            )
            + 2,
        )

    async def fragment(self, sequence: int) -> AudioFragment:
        parts = urlsplit(self.url)
        query = dict(parse_qsl(parts.query))
        query["sq"] = str(sequence)
        url = urlunsplit(parts._replace(query=urlencode(query)))
        try:
            async with self.client.stream("GET", url) as response:
                response.raise_for_status()
                if int(response.headers.get("x-sequence-num", -1)) != sequence:
                    raise SourceError("YouTube zwrócił inny segment niż zamówiony")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 2_000_000:
                        raise SourceError("Segment DVR przekroczył limit 2 MB")
        except httpx.HTTPError:
            # Never skip an unavailable fragment within the DVR window. Re-resolve
            # expiring signed URLs and retry from the durable checkpoint instead.
            raise SourceError(f"Nie udało się pobrać segmentu DVR {sequence}") from None
        return await self.decode(sequence, bytes(data))

    async def decode(self, sequence: int, data: bytes) -> AudioFragment:
        metadata = json.loads(
            await run_process(
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=start_time",
                "-of",
                "json",
                "pipe:0",
                data=data,
            )
        )
        try:
            position = float(metadata["streams"][0]["start_time"])
            if not math.isfinite(position) or position < 0:
                raise ValueError
        except (KeyError, IndexError, ValueError):
            raise SourceError("Brak pozycji audio w segmencie DVR") from None
        pcm = await run_process(
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(self.settings.sample_rate),
            "-t",
            "31",
            "-f",
            "s16le",
            "pipe:1",
            data=data,
        )
        duration = len(pcm) / (2 * self.settings.sample_rate)
        if abs(duration - self.fragment_seconds) > 0.25:
            raise SourceError("Nieprawidłowa długość audio w segmencie DVR")
        return AudioFragment(sequence, round(position * self.settings.sample_rate), pcm)

    async def close(self) -> None:
        await self.client.aclose()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def time_origin(head: Head) -> datetime:
    # Anchor once per stream generation. YouTube's release_timestamp refers to
    # the original watch page, not the current encoder timeline. Wall-clock
    # accuracy is limited to approximately one source fragment.
    return head.observed_at - timedelta(seconds=head.position)
