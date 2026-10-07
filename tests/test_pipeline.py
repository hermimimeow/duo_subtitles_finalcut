from pathlib import Path

from video_workflow.config import Settings
from video_workflow.models import StepStatus, SubtitleCue
from video_workflow.pipeline import Pipeline
from video_workflow.projects import ProjectPaths, ProjectStore
from video_workflow.subtitles import write_srt


class FakeTranscriber:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe(self, audio_path: Path) -> list[SubtitleCue]:
        return [SubtitleCue(1, 0.0, 1.0, "你好")]


class FakeTranslator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def translate(self, cues: list[SubtitleCue], target_language: str) -> list[SubtitleCue]:
        return [
            SubtitleCue(cue.index, cue.start_seconds, cue.end_seconds, f"{target_language}: Hello")
            for cue in cues
        ]


def test_pipeline_status_detects_missing_input(tmp_path: Path) -> None:
    settings = Settings(workspace_dir=tmp_path)
    store = ProjectStore(settings)
    store.create("project_1")
    pipeline = Pipeline(settings, store)

    states = pipeline.status("project_1")

    assert states[0].status == StepStatus.MISSING_INPUT
    assert states[1].status == StepStatus.MISSING_INPUT
    assert states[2].status == StepStatus.MISSING_INPUT
    assert states[3].status == StepStatus.MISSING_INPUT


def test_pipeline_can_transcribe_translate_and_merge_staged_outputs(tmp_path: Path) -> None:
    settings = Settings(workspace_dir=tmp_path)
    store = ProjectStore(settings)
    project = store.create("project_1")
    paths = ProjectPaths(project)
    paths.audio.write_bytes(b"fake mp3")
    pipeline = Pipeline(
        settings,
        store,
        transcriber_factory=FakeTranscriber,
        translator_factory=FakeTranslator,
    )

    transcribe_state = pipeline.run_transcribe("project_1")
    translate_state = pipeline.run_translate("project_1", "en")
    merge_state = pipeline.run_merge("project_1", "en")

    assert transcribe_state.status == StepStatus.COMPLETE
    assert translate_state.status == StepStatus.COMPLETE
    assert merge_state.status == StepStatus.COMPLETE
    assert "你好\n" in paths.final_srt.read_text(encoding="utf-8")
    assert "en: Hello" in paths.final_srt.read_text(encoding="utf-8")


def test_pipeline_skips_completed_transcription_without_force(tmp_path: Path) -> None:
    settings = Settings(workspace_dir=tmp_path)
    store = ProjectStore(settings)
    project = store.create("project_1")
    paths = ProjectPaths(project)
    paths.audio.write_bytes(b"fake mp3")
    write_srt(paths.source_srt, [SubtitleCue(1, 0.0, 1.0, "existing")])
    pipeline = Pipeline(settings, store, transcriber_factory=FakeTranscriber)

    state = pipeline.run_transcribe("project_1", force=False)

    assert state.status == StepStatus.COMPLETE
    assert "existing" in paths.source_srt.read_text(encoding="utf-8")
