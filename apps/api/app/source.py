from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import Settings


class SourceError(RuntimeError):
    pass


def validate_cookies_file(settings: Settings) -> None:
    path = settings.ytdlp_cookies_file
    if path is None:
        return
    # yt-dlp treats a missing cookie file as a new, empty cookie jar. Fail
    # explicitly instead of silently making unauthenticated requests after deploy.
    try:
        with path.open("rb") as cookies:
            if not cookies.read(1):
                raise SourceError("YTDLP_COOKIES_FILE: plik cookies jest pusty")
    except OSError:
        raise SourceError(
            "YTDLP_COOKIES_FILE: plik cookies nie istnieje lub nie jest czytelny; "
            "sprawdź ścieżkę i montowanie trwałego wolumenu",
        ) from None


@dataclass(slots=True)
class ProcessAudioSource:
    settings: Settings
    process: asyncio.subprocess.Process | None = None

    async def open(self) -> None:
        if shutil.which("ffmpeg") is None:
            raise SourceError("Nie znaleziono ffmpeg w PATH")
        input_url = await self._resolve_input()
        command = self._ffmpeg_command(input_url)
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if self.process.stdout is None:
            raise SourceError("FFmpeg nie udostępnił strumienia audio")

    async def _resolve_input(self) -> str:
        if self.settings.source_mode != "youtube":
            return self.settings.source_url
        validate_cookies_file(self.settings)
        if shutil.which("yt-dlp") is None:
            raise SourceError("Nie znaleziono yt-dlp w PATH")
        command = [
            "yt-dlp",
            "--no-warnings",
            "--no-playlist",
            "--format",
            "bestaudio/best",
            "--get-url",
            "--js-runtimes",
            "deno",
        ]
        if self.settings.ytdlp_pot_provider_url:
            command.extend([
                "--extractor-args", "youtube:player_client=mweb",
                "--extractor-args",
                f"youtubepot-bgutilhttp:base_url={self.settings.ytdlp_pot_provider_url}",
            ])
        if self.settings.ytdlp_cookies_file:
            command.extend(["--cookies", str(self.settings.ytdlp_cookies_file)])
        command.append(self.settings.source_url)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode(errors="replace").strip()
            raise SourceError(f"yt-dlp nie rozwiązał transmisji: {message[-500:]}")
        input_url = stdout.decode(errors="replace").strip()
        if not input_url:
            raise SourceError("yt-dlp zwrócił pusty adres transmisji")
        return input_url

    def _ffmpeg_command(self, input_url: str) -> list[str]:
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
        if self.settings.source_mode == "youtube" or input_url.startswith(("http://", "https://")):
            command.extend(
                [
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                ]
            )
        elif self.settings.source_mode == "file":
            command.append("-re")
        command.extend(
            [
                "-i",
                input_url,
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(self.settings.sample_rate),
                "-f",
                "s16le",
                "pipe:1",
            ]
        )
        return command

    async def read(self, size: int = 65_536) -> bytes:
        if self.process is None or self.process.stdout is None:
            raise SourceError("Źródło audio nie zostało otwarte")
        return await self.process.stdout.read(size)

    async def wait(self) -> int:
        if self.process is None:
            return 0
        return await self.process.wait()

    async def close(self) -> None:
        if self.process is None:
            return
        if self.process.returncode is None:
            self.process.terminate()
        try:
            # Drain buffered audio so waiting for FFmpeg cannot deadlock on a full pipe.
            await asyncio.wait_for(self.process.communicate(), timeout=5)
        except TimeoutError:
            if self.process.returncode is None:
                self.process.kill()
            await self.process.communicate()


def validate_source(settings: Settings) -> None:
    if settings.source_mode == "file" and not Path(settings.source_url).is_file():
        raise SourceError(f"Plik źródłowy nie istnieje: {settings.source_url}")
