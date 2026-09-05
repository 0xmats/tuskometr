from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    source_mode: Literal["youtube", "file", "direct"] = "youtube"
    source_url: str = "https://www.youtube.com/watch?v=dzntyCTgJMQ"
    database_url: str = "sqlite:////data/tuskometr.db"
    transcript_retention_days: int = Field(default=30, ge=1, le=3650)
    app_timezone: str = "Europe/Warsaw"

    asr_provider: Literal["local", "ovh"] = "local"
    asr_api_key: SecretStr = SecretStr("")
    asr_api_base_url: str = "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"
    asr_api_model: str = "whisper-large-v3"
    asr_api_timeout_seconds: float = Field(default=60, gt=0, le=300)
    asr_model: str = "small"
    asr_fallback_model: str = "base"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_cpu_threads: int = Field(default=4, ge=1, le=128)
    asr_beam_size: int = Field(default=3, ge=1, le=10)
    asr_hotwords_verify: bool = True

    chunk_seconds: int = Field(default=25, ge=5, le=120)
    chunk_step_seconds: int = Field(default=20, ge=2, le=120)
    sample_rate: int = Field(default=16_000, ge=8_000, le=48_000)
    max_audio_queue_seconds: int = Field(default=90, ge=30, le=900)
    ytdlp_cookies_file: Path | None = None

    frontend_dist: Path = Path("/app/static")
    api_poll_seconds: float = Field(default=2.0, ge=0.5, le=30)

    @field_validator("chunk_step_seconds")
    @classmethod
    def step_must_fit_window(cls, value: int, info):
        window = info.data.get("chunk_seconds", 25)
        if value > window:
            raise ValueError("CHUNK_STEP_SECONDS must not exceed CHUNK_SECONDS")
        return value

    @field_validator("ytdlp_cookies_file", mode="before")
    @classmethod
    def empty_cookie_path_is_none(cls, value):
        return None if value in (None, "") else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
