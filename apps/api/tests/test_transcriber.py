import io
import wave
from unittest.mock import Mock

import httpx
import pytest

from app.config import Settings
from app.transcriber import ApiTranscriber, create_transcriber


def settings(**kwargs):
    return Settings(_env_file=None, asr_provider="ovh", asr_api_key="test-secret", **kwargs)


def test_provider_selection_does_not_load_local_model(monkeypatch):
    local = Mock()
    monkeypatch.setattr("app.transcriber.WhisperTranscriber", local)
    assert isinstance(create_transcriber(settings()), ApiTranscriber)
    local.assert_not_called()
    config = Settings(_env_file=None, asr_provider="local")
    assert create_transcriber(config) is local.return_value
    local.assert_called_once_with(config)


def test_key_required_and_hidden():
    with pytest.raises(ValueError, match="ASR_API_KEY"):
        ApiTranscriber(Settings(_env_file=None, asr_api_key=""))
    assert "test-secret" not in repr(settings())
    with pytest.raises(ValueError, match="HTTPS"):
        ApiTranscriber(settings(asr_api_base_url="http://example.com"))


def test_audio_request_and_timestamp_mapping(monkeypatch):
    post = Mock(
        return_value=httpx.Response(
            200,
            json={
                "text": "Donald Tusk",
                "words": [
                    {"word": "Donald", "start": 0, "end": 0.4},
                    {"word": "Tusk", "start": 0.4, "end": 0.9},
                ],
            },
        )
    )
    monkeypatch.setattr("app.transcriber.httpx.post", post)
    pcm = b"\0\0" * 16000
    result = ApiTranscriber(settings()).transcribe_pcm(pcm)
    assert result.words[1].start == 0.4
    assert result.words[1].probability == 0
    request = post.call_args.kwargs
    assert request["headers"]["Authorization"] == "Bearer test-secret"
    assert request["data"]["language"] == "pl"
    assert request["data"]["timestamp_granularities[]"] == "word"
    assert "prompt" not in request["data"]
    with wave.open(io.BytesIO(request["files"]["file"][1])) as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(16000) == pcm


@pytest.mark.parametrize(
    "body",
    [
        {"text": "Tusk"},
        {"text": "Tusk", "words": []},
        {"text": "Tusk", "words": [{"word": "Tusk", "start": 1, "end": 0}]},
        {"text": "Tusk", "words": [{"word": "Tusk", "start": 0, "end": 99}]},
    ],
)
def test_rejects_invalid_response(monkeypatch, body):
    monkeypatch.setattr(
        "app.transcriber.httpx.post", Mock(return_value=httpx.Response(200, json=body))
    )
    with pytest.raises(RuntimeError, match="timestampy"):
        ApiTranscriber(settings()).transcribe_pcm(b"\0\0" * 16000)


@pytest.mark.parametrize("status", [401, 429, 500, 302])
def test_http_errors_are_sanitized_and_not_retried(monkeypatch, status):
    post = Mock(return_value=httpx.Response(status, text="test-secret private transcript"))
    monkeypatch.setattr("app.transcriber.httpx.post", post)
    with pytest.raises(RuntimeError, match=f"HTTP {status}") as error:
        ApiTranscriber(settings()).transcribe_pcm(b"\0\0" * 16000)
    assert "test-secret" not in str(error.value)
    assert post.call_count == 1


def test_timeout_and_silence(monkeypatch):
    post = Mock(side_effect=httpx.ReadTimeout("private details"))
    monkeypatch.setattr("app.transcriber.httpx.post", post)
    transcriber = ApiTranscriber(settings())
    assert transcriber.transcribe_pcm(b"").words == []
    post.assert_not_called()
    with pytest.raises(RuntimeError, match="połączenia"):
        transcriber.transcribe_pcm(b"\0\0")
    post.side_effect = None
    post.return_value = httpx.Response(200, json={"text": "", "words": []})
    assert transcriber.transcribe_pcm(b"\0\0").words == []


def test_fuzzy_verification_crops_audio_and_uses_prompt(monkeypatch):
    transcriber = ApiTranscriber(settings())
    post = Mock(
        return_value=httpx.Response(
            200,
            json={
                "text": "Tuska",
                "words": [{"word": "Tuska", "start": 6, "end": 7}],
            },
        )
    )
    monkeypatch.setattr("app.transcriber.httpx.post", post)
    assert transcriber.verify_fuzzy_candidate(b"\0\0" * 320000, 10, 11) == ("tuska", 0)
    request = post.call_args.kwargs
    assert "Tusk" in request["data"]["prompt"]
    with wave.open(io.BytesIO(request["files"]["file"][1])) as wav:
        assert wav.getnframes() == 13 * 16000


def test_five_minute_audio_preserves_word_timestamps(monkeypatch):
    post = Mock(return_value=httpx.Response(200, json={
        "text": "Tusk", "words": [{"word": "Tusk", "start": 297, "end": 297.5}],
    }))
    monkeypatch.setattr("app.transcriber.httpx.post", post)
    pcm = b"\0\0" * (300 * 16000)
    result = ApiTranscriber(settings()).transcribe_pcm(pcm)
    assert result.words[0].start == 297
    assert result.words[0].end == 297.5
    post.assert_called_once()
    with wave.open(io.BytesIO(post.call_args.kwargs["files"]["file"][1])) as wav:
        assert wav.getnframes() == 300 * 16000
        assert wav.getframerate() == 16000
