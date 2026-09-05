from __future__ import annotations

import io
import math
import wave
from dataclasses import dataclass
from typing import Protocol

import httpx
import numpy as np
from pydantic import BaseModel, Field, ValidationError, model_validator

from .config import Settings
from .detection import CANONICAL_FORMS, HOTWORDS, WordToken, normalize_token


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    words: list[WordToken]
    average_confidence: float


class Transcriber(Protocol):
    model_name: str

    def transcribe_pcm(self, pcm: bytes) -> TranscriptionResult: ...

    def verify_fuzzy_candidate(
        self, pcm: bytes, candidate_start: float, candidate_end: float
    ) -> tuple[str, float] | None: ...


def create_transcriber(settings: Settings) -> Transcriber:
    if settings.asr_provider == "ovh":
        return ApiTranscriber(settings)
    return WhisperTranscriber(settings)


class ApiWord(BaseModel):
    word: str
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    # OVH does not expose word probability: 0 means unavailable in our numeric schema.
    probability: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("Invalid word timestamps")
        return self


class ApiTranscript(BaseModel):
    text: str
    words: list[ApiWord]


class ApiTranscriber:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_name = settings.asr_api_model
        if not settings.asr_api_key.get_secret_value().strip():
            raise ValueError("ASR_API_KEY jest wymagany dla ASR_PROVIDER=ovh")
        url = httpx.URL(settings.asr_api_base_url)
        if url.scheme != "https" or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError("ASR_API_BASE_URL musi być adresem HTTPS bez danych logowania")
        self.url = str(url).rstrip("/") + "/audio/transcriptions"

    def transcribe_pcm(self, pcm: bytes) -> TranscriptionResult:
        return self._transcribe(pcm)

    def _transcribe(self, pcm: bytes, prompt: str | None = None) -> TranscriptionResult:
        if len(pcm) % 2:
            raise ValueError("Audio musi być PCM signed 16-bit mono")
        if not pcm:
            return TranscriptionResult("", [], 0.0)
        audio = io.BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.settings.sample_rate)
            wav.writeframes(pcm)
        data = {
            "model": self.model_name,
            "language": "pl",
            "temperature": "0",
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        if prompt:
            data["prompt"] = prompt
        # No automatic retries: a timed-out request may already have been billed.
        try:
            response = httpx.post(
                self.url,
                headers={"Authorization": f"Bearer {self.settings.asr_api_key.get_secret_value()}"},
                data=data,
                files={"file": ("audio.wav", audio.getvalue(), "audio/wav")},
                timeout=self.settings.asr_api_timeout_seconds,
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise RuntimeError("Błąd połączenia z API transkrypcji") from None
        if response.status_code != 200:
            # Do not expose response bodies (audio text, credentials) in worker status/logs.
            raise RuntimeError(f"API transkrypcji zwróciło HTTP {response.status_code}")
        try:
            payload = ApiTranscript.model_validate(response.json())
            duration = len(pcm) / (2 * self.settings.sample_rate)
            if payload.text.strip() and not payload.words:
                raise ValueError("Missing word timestamps")
            if any(word.end > duration + 0.1 for word in payload.words):
                raise ValueError("Word outside audio")
        except (ValueError, ValidationError):
            raise RuntimeError(
                "Nieprawidłowa odpowiedź API: wymagany tekst i timestampy słów"
            ) from None
        words = [WordToken(w.word.strip(), w.start, w.end, w.probability) for w in payload.words]
        confidence = math.fsum(w.probability for w in words) / len(words) if words else 0.0
        return TranscriptionResult(payload.text.strip(), words, confidence)

    def verify_fuzzy_candidate(
        self, pcm: bytes, candidate_start: float, candidate_end: float
    ) -> tuple[str, float] | None:
        start = max(0, int((candidate_start - 6) * self.settings.sample_rate)) * 2
        end = min(len(pcm), int((candidate_end + 6) * self.settings.sample_rate) * 2)
        if end <= start:
            return None
        result = self._transcribe(
            pcm[start:end], HOTWORDS if self.settings.asr_hotwords_verify else None
        )
        for word in result.words:
            normalized = normalize_token(word.text)
            if normalized in CANONICAL_FORMS:
                return normalized, word.probability
        return None


class WhisperTranscriber:
    def __init__(self, settings: Settings, model_name: str | None = None) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "Pakiet faster-whisper nie jest zainstalowany. Zainstaluj zależności backendu."
            ) from error

        self.settings = settings
        self.model_name = model_name or settings.asr_model
        self.model = WhisperModel(
            self.model_name,
            device=settings.asr_device,
            compute_type=settings.asr_compute_type,
            cpu_threads=settings.asr_cpu_threads,
        )

    @staticmethod
    def pcm_to_float32(pcm: bytes) -> np.ndarray:
        return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    def transcribe_pcm(self, pcm: bytes) -> TranscriptionResult:
        return self._transcribe(self.pcm_to_float32(pcm), hotwords=None, beam_size=None)

    def verify_fuzzy_candidate(
        self, pcm: bytes, candidate_start: float, candidate_end: float
    ) -> tuple[str, float] | None:
        sample_rate = self.settings.sample_rate
        audio = self.pcm_to_float32(pcm)
        start = max(0, int((candidate_start - 6) * sample_rate))
        end = min(len(audio), int((candidate_end + 6) * sample_rate))
        if end <= start:
            return None
        result = self._transcribe(
            audio[start:end],
            hotwords=HOTWORDS if self.settings.asr_hotwords_verify else None,
            beam_size=max(5, self.settings.asr_beam_size),
        )
        for word in result.words:
            normalized = normalize_token(word.text)
            if normalized in CANONICAL_FORMS:
                return normalized, word.probability
        return None

    def _transcribe(
        self, audio: np.ndarray, hotwords: str | None, beam_size: int | None
    ) -> TranscriptionResult:
        segments, _info = self.model.transcribe(
            audio,
            language="pl",
            beam_size=beam_size or self.settings.asr_beam_size,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False,
            hotwords=hotwords,
        )
        texts: list[str] = []
        words: list[WordToken] = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                texts.append(text)
            if segment.words:
                for word in segment.words:
                    words.append(
                        WordToken(
                            text=word.word.strip(),
                            start=float(word.start),
                            end=float(word.end),
                            probability=float(word.probability),
                        )
                    )
        confidence = sum(word.probability for word in words) / len(words) if words else 0.0
        return TranscriptionResult(text=" ".join(texts), words=words, average_confidence=confidence)
