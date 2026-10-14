from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class StepName(str, Enum):
    """Pipeline step names, in the order the steps run."""
    EXTRACT = "extract"
    TRANSCRIBE = "transcribe"
    TRANSLATE = "translate"
    MERGE = "merge"


class StepStatus(str, Enum):
    """How ready a step is: complete, ready, missing input, invalid, or failed."""
    MISSING_INPUT = "missing_input"
    READY = "ready"
    COMPLETE = "complete"
    INVALID = "invalid"
    FAILED = "failed"


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


@dataclass(frozen=True)
class ProjectMetadata:
    """Durable project settings stored in project.json."""
    id: str
    source_video: str | None = None
    source_language: str = "yue"
    target_language: str = "en"
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def new(cls, project_id: str, source_language: str, target_language: str) -> "ProjectMetadata":
        """Create metadata with created and updated timestamps set to now (UTC)."""
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
    """A project: its id, its folder, and its loaded metadata."""
    id: str
    root: Path
    metadata: ProjectMetadata


@dataclass(frozen=True)
class SubtitleCue:
    """One subtitle entry: its index, start and end times in seconds, and text."""
    index: int
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class StepState:
    """What one pipeline step looks like right now: status, paths, and a message for the user."""
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
        """True when the step's output exists and is valid."""
        return self.status == StepStatus.COMPLETE
