from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared, fallback helps tests.
    load_dotenv = None


@dataclass(frozen=True)
class Settings:
    workspace_dir: Path = Path("workspace")
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    whisper_language: str | None = None
    default_source_language: str = "yue"
    default_target_language: str = "en"
    ffmpeg_binary: str = "ffmpeg"
    web_host: str = "127.0.0.1"
    web_port: int = 8000


def load_settings(env_file: Path | str | None = ".env") -> Settings:
    if load_dotenv is not None and env_file:
        load_dotenv(env_file)

    return Settings(
        workspace_dir=Path(os.getenv("WORKSPACE_DIR", "workspace")),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        whisper_model=os.getenv("WHISPER_MODEL", "large-v3"),
        whisper_device=os.getenv("WHISPER_DEVICE", "auto"),
        whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "auto"),
        whisper_language=_empty_to_none(os.getenv("WHISPER_LANGUAGE")),
        default_source_language=os.getenv("DEFAULT_SOURCE_LANGUAGE", "yue"),
        default_target_language=os.getenv("DEFAULT_TARGET_LANGUAGE", "en"),
        ffmpeg_binary=os.getenv("FFMPEG_BINARY", "ffmpeg"),
        web_host=os.getenv("WEB_HOST", "127.0.0.1"),
        web_port=int(os.getenv("WEB_PORT", "8000")),
    )


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
