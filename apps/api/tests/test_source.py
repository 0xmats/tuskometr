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


def test_direct_source_does_not_use_youtube_resolver() -> None:
    source = ProcessAudioSource(Settings(
        _env_file=None,
        source_mode="direct",
        source_url="https://example.test/live.m3u8",
    ))
    with patch("app.source.asyncio.create_subprocess_exec") as launch:
        assert asyncio.run(source._resolve_input()) == "https://example.test/live.m3u8"
    launch.assert_not_called()


def test_closing_source_drains_buffered_audio() -> None:
    import sys

    async def exercise():
        source = ProcessAudioSource(Settings(_env_file=None))
        source.process = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            "import os; os.write(1, b'x' * 1048576)",
            stdout=asyncio.subprocess.PIPE,
        )
        # Let output back up in the pipe before stopping the source.
        await asyncio.wait_for(source.process.stdout.read(1), timeout=5)
        await asyncio.sleep(0.1)
        await asyncio.wait_for(source.close(), timeout=8)
        assert source.process.returncode is not None

    asyncio.run(exercise())


def test_youtube_proxy_covers_resolver_and_ffmpeg_but_not_direct_sources():
    proxy = "http://home.test:18888"
    settings = Settings(_env_file=None, youtube_proxy_url=proxy)
    source = ProcessAudioSource(settings)
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (b"https://example.test/audio\n", b"")
    with patch("app.source.shutil.which", return_value="/usr/bin/tool"), patch(
        "app.source.asyncio.create_subprocess_exec", return_value=process,
    ) as launch:
        url = asyncio.run(source._resolve_input())
    args = launch.call_args.args
    assert args[args.index("--proxy") + 1] == proxy
    assert "--cookies" not in args
    assert "--no-plugin-dirs" in args
    assert "--extractor-args" not in args
    args = source._ffmpeg_command(url)
    assert args[args.index("-http_proxy") + 1] == proxy
    assert args.index("-http_proxy") < args.index("-i")
    settings.source_mode = "direct"
    assert "-http_proxy" not in source._ffmpeg_command(url)


def test_proxy_error_redacts_credentials():
    from app.source import process_error

    message = process_error(b"Cannot connect to http://user:private-password@home.test:18888")
    assert "private-password" not in message
    assert "Cannot connect" in message


def test_proxy_configuration_rejects_unsupported_schemes():
    import pytest
    from pydantic import ValidationError

    for proxy in ("socks5://home:1080", "https://home:443", "http://home", "http://home:bad"):
        with pytest.raises(ValidationError, match="HTTP proxy URL"):
            Settings(_env_file=None, youtube_proxy_url=proxy)
