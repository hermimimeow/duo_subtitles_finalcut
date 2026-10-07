from __future__ import annotations

import re
from pathlib import Path

from video_workflow.models import SubtitleCue

TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


class SubtitleError(RuntimeError):
    pass


def format_timestamp(seconds: float) -> str:
    if seconds < 0:
        raise ValueError("Subtitle timestamp cannot be negative")
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def parse_timestamp(value: str) -> float:
    try:
        clock, millis = value.split(",")
        hours, minutes, seconds = clock.split(":")
    except ValueError as error:
        raise SubtitleError(f"Invalid SRT timestamp: {value}") from error
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000
    )


def render_srt(cues: list[SubtitleCue] | tuple[SubtitleCue, ...]) -> str:
    blocks: list[str] = []
    for output_index, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join(
                [
                    str(output_index),
                    f"{format_timestamp(cue.start_seconds)} --> {format_timestamp(cue.end_seconds)}",
                    cue.text.strip(),
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def write_srt(path: Path, cues: list[SubtitleCue] | tuple[SubtitleCue, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_srt(cues), encoding="utf-8")


def parse_srt_text(text: str) -> list[SubtitleCue]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    cues: list[SubtitleCue] = []
    blocks = re.split(r"\n{2,}", normalized)
    for block in blocks:
        lines = block.split("\n")
        if len(lines) < 3:
            raise SubtitleError(f"Invalid SRT block: {block!r}")

        try:
            index = int(lines[0].strip())
        except ValueError as error:
            raise SubtitleError(f"Invalid SRT cue index: {lines[0]!r}") from error

        match = TIMESTAMP_RE.match(lines[1].strip())
        if not match:
            raise SubtitleError(f"Invalid SRT timestamp line: {lines[1]!r}")

        start_seconds = parse_timestamp(match.group("start"))
        end_seconds = parse_timestamp(match.group("end"))
        if end_seconds <= start_seconds:
            raise SubtitleError(f"Cue {index} end timestamp must be after start timestamp")

        cue_text = "\n".join(lines[2:]).strip()
        if not cue_text:
            raise SubtitleError(f"Cue {index} has empty text")

        cues.append(SubtitleCue(index, start_seconds, end_seconds, cue_text))
    return cues


def read_srt(path: Path) -> list[SubtitleCue]:
    if not path.exists():
        raise FileNotFoundError(path)
    return parse_srt_text(path.read_text(encoding="utf-8"))


def validate_srt(path: Path) -> bool:
    try:
        return bool(read_srt(path))
    except (OSError, SubtitleError, UnicodeDecodeError):
        return False


def cues_aligned(left: list[SubtitleCue], right: list[SubtitleCue], tolerance: float = 0.001) -> bool:
    if len(left) != len(right):
        return False
    for left_cue, right_cue in zip(left, right):
        if abs(left_cue.start_seconds - right_cue.start_seconds) > tolerance:
            return False
        if abs(left_cue.end_seconds - right_cue.end_seconds) > tolerance:
            return False
    return True


def merge_cues(
    source_cues: list[SubtitleCue],
    translated_cues: list[SubtitleCue],
) -> list[SubtitleCue]:
    if not cues_aligned(source_cues, translated_cues):
        raise SubtitleError("Source and translated subtitles are not aligned")

    merged: list[SubtitleCue] = []
    for index, (source, translated) in enumerate(zip(source_cues, translated_cues), start=1):
        merged.append(
            SubtitleCue(
                index=index,
                start_seconds=source.start_seconds,
                end_seconds=source.end_seconds,
                text=f"{source.text.strip()}\n{translated.text.strip()}",
            )
        )
    return merged
