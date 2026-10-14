from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from video_workflow.config import Settings
from video_workflow.models import Project, ProjectMetadata, SUPPORTED_VIDEO_EXTENSIONS

PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ProjectError(RuntimeError):
    """Raised for invalid project ids, missing projects, or unusable source video settings."""
    pass


class ProjectPaths:
    """Paths inside a project folder.

    Target-language paths use target_language, which defaults to the project's target.
    """
    def __init__(self, project: Project, target_language: str | None = None) -> None:
        """Store the project and the target language to use for its paths."""
        self.project = project
        self.target_language = target_language or project.metadata.target_language

    @property
    def root(self) -> Path:
        """The project folder."""
        return self.project.root

    @property
    def metadata(self) -> Path:
        """Path to project.json."""
        return self.root / "project.json"

    @property
    def video_dir(self) -> Path:
        """Folder where the source video is staged."""
        return self.root / "video"

    @property
    def audio_dir(self) -> Path:
        """Folder for the extracted MP3."""
        return self.root / "audio"

    @property
    def subtitles_dir(self) -> Path:
        """Folder for the source, translated and final SRT files."""
        return self.root / "subtitles"

    @property
    def logs_dir(self) -> Path:
        """Folder for the step logs."""
        return self.root / "logs"

    @property
    def tmp_dir(self) -> Path:
        """Folder for partial outputs, before they replace the final files."""
        return self.root / "tmp"

    @property
    def audio(self) -> Path:
        """Path to the extracted MP3."""
        return self.audio_dir / f"{self.project.id}.mp3"

    @property
    def source_srt(self) -> Path:
        """Path to the source-language SRT."""
        return self.subtitles_dir / f"{self.project.id}.{self.project.metadata.source_language}.srt"

    @property
    def translated_srt(self) -> Path:
        """Path to the translated SRT for the target language."""
        return self.subtitles_dir / f"{self.project.id}.{self.target_language}.srt"

    @property
    def final_srt(self) -> Path:
        """Path to the bilingual SRT for the target language."""
        return self.subtitles_dir / f"{self.project.id}.{self.target_language}.final.srt"

    @property
    def extract_log(self) -> Path:
        """Log file for the extract step."""
        return self.logs_dir / "extract-audio.log"

    @property
    def transcribe_log(self) -> Path:
        """Log file for the transcribe step."""
        return self.logs_dir / "transcribe.log"

    @property
    def translate_log(self) -> Path:
        """Log file for the translate step."""
        return self.logs_dir / f"translate-{self.target_language}.log"

    @property
    def merge_log(self) -> Path:
        """Log file for the merge step."""
        return self.logs_dir / f"merge-{self.target_language}.log"

    def ensure_dirs(self) -> None:
        """Create the project's standard folders if they do not exist."""
        for directory in (
            self.video_dir,
            self.audio_dir,
            self.subtitles_dir,
            self.logs_dir,
            self.tmp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


class ProjectStore:
    """Finds, creates and reads projects in the workspace folder."""
    def __init__(self, settings: Settings) -> None:
        """Store the settings; the workspace folder comes from them."""
        self.settings = settings
        self.workspace_dir = settings.workspace_dir

    def ensure_workspace(self) -> None:
        """Create the workspace folder if it does not exist."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[Project]:
        """Return every project folder in the workspace, sorted by name.

        Hidden folders are skipped.
        """
        self.ensure_workspace()
        projects: list[Project] = []
        for path in sorted(self.workspace_dir.iterdir()):
            if path.is_dir() and not path.name.startswith("."):
                projects.append(self.load(path.name))
        return projects

    def create(self, project_id: str) -> Project:
        """Create a project, or fill in the folders and project.json of an existing one.

        This is the only place project files are written.
        """
        validate_project_id(project_id)
        self.ensure_workspace()
        root = self.workspace_dir / project_id
        root.mkdir(parents=True, exist_ok=True)

        project = self.load(project_id)
        paths = ProjectPaths(project)
        paths.ensure_dirs()
        if not paths.metadata.exists():
            metadata = ProjectMetadata.new(
                project_id,
                self.settings.default_source_language,
                self.settings.default_target_language,
            )
            write_metadata(paths.metadata, metadata)
            project = Project(project_id, root, metadata)
        return project

    def load(self, project_id: str) -> Project:
        """Read a project without writing to disk."""
        validate_project_id(project_id)
        root = self.workspace_dir / project_id
        if not root.exists() or not root.is_dir():
            raise ProjectError(f"Project not found: {project_id}")

        metadata_path = root / "project.json"
        if metadata_path.exists():
            metadata = read_metadata(metadata_path)
        else:
            metadata = ProjectMetadata(
                id=project_id,
                source_language=self.settings.default_source_language,
                target_language=self.settings.default_target_language,
            )
        return Project(project_id, root, metadata)

    def find_source_video(self, project: Project) -> Path:
        """Return the source video for a project.

        Uses source_video from project.json if set, otherwise the single supported video in video/.
        Raises ProjectError if none or several are found.
        """
        paths = ProjectPaths(project)

        if project.metadata.source_video:
            selected = project.root / project.metadata.source_video
            if not selected.exists():
                raise ProjectError(f"Configured source video does not exist: {selected}")
            if selected.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
                raise ProjectError(f"Configured source video has unsupported extension: {selected}")
            return selected

        videos = [
            path
            for path in (sorted(paths.video_dir.iterdir()) if paths.video_dir.is_dir() else [])
            if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
        ]
        if not videos:
            raise ProjectError(f"No supported video file found in {paths.video_dir}")
        if len(videos) > 1:
            names = ", ".join(path.name for path in videos)
            raise ProjectError(
                "Multiple video files found. Set source_video in project.json. "
                f"Candidates: {names}"
            )
        return videos[0]


def validate_project_id(project_id: str) -> None:
    """Raise ProjectError unless project_id is a safe folder name."""
    if not PROJECT_ID_PATTERN.match(project_id):
        raise ProjectError(
            "Project id must start with a letter or number and contain only letters, "
            "numbers, dots, underscores, or hyphens."
        )


def read_metadata(path: Path) -> ProjectMetadata:
    """Read project.json, filling in defaults for missing fields."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return ProjectMetadata(
        id=str(data.get("id") or path.parent.name),
        source_video=data.get("source_video"),
        source_language=str(data.get("source_language") or "yue"),
        target_language=str(data.get("target_language") or "en"),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
    )


def write_metadata(path: Path, metadata: ProjectMetadata) -> None:
    """Write metadata to project.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(metadata), indent=2) + "\n", encoding="utf-8")
