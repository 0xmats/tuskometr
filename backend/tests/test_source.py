import asyncio
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.source import ProcessAudioSource


def test_youtube_source_resolves_to_direct_stream_url() -> None:
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (
        b"https://example.test/live.m3u8\n",
        b"",
    )
    source = ProcessAudioSource(
        Settings(
            source_mode="youtube",
            source_url="https://www.youtube.com/watch?v=test",
            database_url="sqlite://",
        )
    )

    with patch("app.source.asyncio.create_subprocess_exec", return_value=process):
        url = asyncio.run(source._resolve_input())

    assert url == "https://example.test/live.m3u8"
