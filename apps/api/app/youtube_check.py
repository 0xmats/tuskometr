"""Probe actual DVR audio without touching the database or running transcription."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from .config import Settings
from .dvr import YoutubeDvrSource
from .source import process_error


async def check(settings: Settings) -> tuple[int, int]:
    source = YoutubeDvrSource(settings)
    try:
        head = await source.open()
        fragment = await source.fragment(max(0, head.sequence - 3))
        if not fragment.pcm:
            raise RuntimeError("DVR returned empty audio")
        return head.sequence, len(fragment.pcm)
    finally:
        await source.close()


async def run(settings: Settings, attempts: int, interval: float) -> int:
    failures = 0
    for attempt in range(attempts):
        stamp = datetime.now(UTC).isoformat()
        try:
            sequence, size = await check(settings)
            print(
                f"{stamp} OK {attempt + 1}/{attempts} sequence={sequence} bytes={size}",
                flush=True,
            )
        except Exception as error:
            failures += 1
            detail = process_error(str(error).encode())
            print(f"{stamp} FAIL {attempt + 1}/{attempts} {detail}", flush=True)
        if attempt + 1 < attempts:
            await asyncio.sleep(interval)
    print(f"Completed: attempts={attempts} failures={failures}", flush=True)
    return int(failures > 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1800)
    args = parser.parse_args()
    if args.attempts < 1 or not 60 <= args.interval <= 86400:
        parser.error("attempts must be positive and interval must be between 60 and 86400 seconds")
    settings = Settings()
    if settings.source_mode != "youtube":
        print("YouTube check skipped: a different source is configured", flush=True)
        return
    print(
        f"DVR check: proxy={bool(settings.youtube_proxy_url.get_secret_value())} "
        "authentication=anonymous plugins=disabled",
        flush=True,
    )
    raise SystemExit(asyncio.run(run(settings, args.attempts, args.interval)))


if __name__ == "__main__":
    main()
