from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class StepName(str, Enum):
    EXTRACT = "extract"
    TRANSCRIBE = "transcribe"
    TRANSLATE = "translate"
    MERGE = "merge"


class StepStatus(str, Enum):
    MISSING_INPUT = "missing_input"
    READY = "ready"
    COMPLETE = "complete"
    INVALID = "invalid"
    FAILED = "failed"


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav"}


@dataclass(frozen=True)
class ProjectMetadata:
    id: str
    source_video: str | None = None
    source_language: str = "yue"
    target_language: str = "en"
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def new(cls, project_id: str, source_language: str, target_language: str) -> "ProjectMetadata":
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return cls(
            id=project_id,
            source_language=source_language,
            target_language=target_language,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class Project:
    id: str
    root: Path
    metadata: ProjectMetadata


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class StepState:
    name: StepName
    status: StepStatus
    input_paths: tuple[Path, ...]
    output_paths: tuple[Path, ...]
    log_path: Path
    can_run: bool
    can_rerun: bool
    message: str

    @property
    def is_complete(self) -> bool:
        return self.status == StepStatus.COMPLETE
