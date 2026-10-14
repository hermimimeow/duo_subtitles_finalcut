from __future__ import annotations

import subprocess
from pathlib import Path

from video_workflow.models import SUPPORTED_VIDEO_EXTENSIONS


def build_ffmpeg_audio_command(ffmpeg_binary: str, input_path: Path, output_path: Path) -> list[str]:
    """Build the ffmpeg command that extracts 16 kHz mono MP3 audio from a video."""
    return [
        ffmpeg_binary,
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        "-f",
        "mp3",
        str(output_path),
    ]


def extract_audio(
    input_path: Path,
    output_path: Path,
    ffmpeg_binary: str = "ffmpeg",
) -> subprocess.CompletedProcess[str]:
    """Extract audio from a video into an MP3 file using ffmpeg.

    Raises CalledProcessError if ffmpeg fails.
    """
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if input_path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ValueError(f"Unsupported video format: {input_path.suffix}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_audio_command(ffmpeg_binary, input_path, output_path)
    return subprocess.run(command, check=True, capture_output=True, text=True)
