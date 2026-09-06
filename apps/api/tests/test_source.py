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


def test_youtube_source_uses_automatic_token_provider(tmp_path) -> None:
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (b"https://example.test/audio\n", b"")
    cookies = tmp_path / "cookies.txt"
    source = ProcessAudioSource(Settings(
        _env_file=None,
        ytdlp_pot_provider_url="http://youtube-tokens:4416",
        ytdlp_cookies_file=cookies,
    ))
    with patch("app.source.shutil.which", return_value="/usr/bin/tool"), patch(
        "app.source.asyncio.create_subprocess_exec", return_value=process,
    ) as launch:
        assert asyncio.run(source._resolve_input()) == "https://example.test/audio"
    args = launch.call_args.args
    assert args[args.index("--js-runtimes") + 1] == "deno"
    assert "youtube:player_client=mweb" in args
    assert "youtubepot-bgutilhttp:base_url=http://youtube-tokens:4416" in args
    assert args[args.index("--cookies") + 1] == str(cookies)


def test_direct_source_does_not_use_youtube_token_provider() -> None:
    source = ProcessAudioSource(Settings(
        _env_file=None,
        source_mode="direct",
        source_url="https://example.test/live.m3u8",
        ytdlp_pot_provider_url="http://youtube-tokens:4416",
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
