from __future__ import annotations

import os
import subprocess
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable

from video_workflow.audio import extract_audio
from video_workflow.config import Settings
from video_workflow.models import Project, StepName, StepState, StepStatus
from video_workflow.projects import ProjectPaths, ProjectStore
from video_workflow.subtitles import (
    cues_aligned,
    merge_cues,
    read_srt,
    validate_srt,
    write_srt,
)
from video_workflow.transcription import FasterWhisperTranscriber
from video_workflow.translation import GeminiTranslator


class PipelineError(RuntimeError):
    pass


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        store: ProjectStore | None = None,
        transcriber_factory: Callable[[Settings], FasterWhisperTranscriber] = FasterWhisperTranscriber,
        translator_factory: Callable[[Settings], GeminiTranslator] = GeminiTranslator,
    ) -> None:
        self.settings = settings
        self.store = store or ProjectStore(settings)
        self.transcriber_factory = transcriber_factory
        self.translator_factory = translator_factory

    def status(self, project_id: str, target_language: str | None = None) -> list[StepState]:
        project = self.store.load(project_id)
        paths = ProjectPaths(project, target_language)
        return [
            self.extract_state(project, paths),
            self.transcribe_state(paths),
            self.translate_state(paths),
            self.merge_state(paths),
        ]

    def extract_state(self, project: Project, paths: ProjectPaths) -> StepState:
        source_video: Path | None = None
        message = ""
        try:
            source_video = self.store.find_source_video(project)
        except Exception as error:
            message = str(error)

        output_valid = paths.audio.exists() and paths.audio.stat().st_size > 0
        if output_valid:
            status = StepStatus.COMPLETE
            can_run = True
            message = f"Audio exists: {paths.audio.name}"
        elif source_video is None:
            status = StepStatus.MISSING_INPUT
            can_run = False
        else:
            status = StepStatus.READY
            can_run = True
            message = f"Ready to extract from {source_video.name}"

        return StepState(
            name=StepName.EXTRACT,
            status=status,
            input_paths=tuple(path for path in (source_video,) if path is not None),
            output_paths=(paths.audio,),
            log_path=paths.extract_log,
            can_run=can_run,
            can_rerun=output_valid,
            message=message,
        )

    def transcribe_state(self, paths: ProjectPaths) -> StepState:
        audio_ready = paths.audio.exists() and paths.audio.stat().st_size > 0
        output_valid = validate_srt(paths.source_srt)

        if output_valid:
            status = StepStatus.COMPLETE
            can_run = True
            message = f"Source subtitles exist: {paths.source_srt.name}"
        elif not audio_ready:
            status = StepStatus.MISSING_INPUT
            can_run = False
            message = f"Missing audio: {paths.audio.name}"
        elif paths.source_srt.exists():
            status = StepStatus.INVALID
            can_run = True
            message = f"Source subtitle exists but is invalid: {paths.source_srt.name}"
        else:
            status = StepStatus.READY
            can_run = True
            message = "Ready to transcribe"

        return StepState(
            name=StepName.TRANSCRIBE,
            status=status,
            input_paths=(paths.audio,),
            output_paths=(paths.source_srt,),
            log_path=paths.transcribe_log,
            can_run=can_run,
            can_rerun=output_valid,
            message=message,
        )

    def translate_state(self, paths: ProjectPaths) -> StepState:
        source_valid = validate_srt(paths.source_srt)
        translated_valid = False
        if paths.translated_srt.exists():
            translated_valid = self._translated_output_valid(paths)

        if translated_valid:
            status = StepStatus.COMPLETE
            can_run = True
            message = f"Translated subtitles exist: {paths.translated_srt.name}"
        elif not source_valid:
            status = StepStatus.MISSING_INPUT
            can_run = False
            message = f"Missing valid source subtitles: {paths.source_srt.name}"
        elif paths.translated_srt.exists():
            status = StepStatus.INVALID
            can_run = True
            message = f"Translated subtitle exists but is invalid: {paths.translated_srt.name}"
        else:
            status = StepStatus.READY
            can_run = True
            message = "Ready to translate"

        return StepState(
            name=StepName.TRANSLATE,
            status=status,
            input_paths=(paths.source_srt,),
            output_paths=(paths.translated_srt,),
            log_path=paths.translate_log,
            can_run=can_run,
            can_rerun=translated_valid,
            message=message,
        )

    def merge_state(self, paths: ProjectPaths) -> StepState:
        inputs_valid = validate_srt(paths.source_srt) and self._translated_output_valid(paths)
        output_valid = validate_srt(paths.final_srt)
        if output_valid and inputs_valid:
            output_valid = self._final_output_valid(paths)

        if output_valid:
            status = StepStatus.COMPLETE
            can_run = True
            message = f"Final subtitles exist: {paths.final_srt.name}"
        elif not inputs_valid:
            status = StepStatus.MISSING_INPUT
            can_run = False
            message = "Missing valid source or translated subtitles"
        elif paths.final_srt.exists():
            status = StepStatus.INVALID
            can_run = True
            message = f"Final subtitle exists but is invalid: {paths.final_srt.name}"
        else:
            status = StepStatus.READY
            can_run = True
            message = "Ready to merge"

        return StepState(
            name=StepName.MERGE,
            status=status,
            input_paths=(paths.source_srt, paths.translated_srt),
            output_paths=(paths.final_srt,),
            log_path=paths.merge_log,
            can_run=can_run,
            can_rerun=output_valid,
            message=message,
        )

    def run_extract(self, project_id: str, force: bool = False) -> StepState:
        project = self.store.load(project_id)
        paths = ProjectPaths(project)
        state = self.extract_state(project, paths)
        if state.is_complete and not force:
            return state
        if not state.can_run:
            raise PipelineError(state.message)

        source_video = self.store.find_source_video(project)
        tmp_output = paths.tmp_dir / f"{paths.audio.name}.tmp"

        def operation() -> None:
            result = extract_audio(source_video, tmp_output, self.settings.ffmpeg_binary)
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr)
            _require_nonempty_file(tmp_output, "audio extraction produced an empty file")

        self._run_logged(paths.extract_log, operation)
        _replace_file(tmp_output, paths.audio)
        return self.extract_state(project, paths)

    def run_transcribe(self, project_id: str, force: bool = False) -> StepState:
        project = self.store.load(project_id)
        paths = ProjectPaths(project)
        state = self.transcribe_state(paths)
        if state.is_complete and not force:
            return state
        if not state.can_run:
            raise PipelineError(state.message)

        tmp_output = paths.tmp_dir / f"{paths.source_srt.name}.tmp"

        def operation() -> None:
            cues = self.transcriber_factory(self.settings).transcribe(paths.audio)
            write_srt(tmp_output, cues)
            if not validate_srt(tmp_output):
                raise PipelineError("transcription produced invalid SRT")

        self._run_logged(paths.transcribe_log, operation)
        _replace_file(tmp_output, paths.source_srt)
        return self.transcribe_state(paths)

    def run_translate(
        self,
        project_id: str,
        target_language: str | None = None,
        force: bool = False,
    ) -> StepState:
        project = self.store.load(project_id)
        target = target_language or project.metadata.target_language
        paths = ProjectPaths(project, target)
        state = self.translate_state(paths)
        if state.is_complete and not force:
            return state
        if not state.can_run:
            raise PipelineError(state.message)

        tmp_output = paths.tmp_dir / f"{paths.translated_srt.name}.tmp"

        def operation() -> None:
            source_cues = read_srt(paths.source_srt)
            translated_cues = self.translator_factory(self.settings).translate(source_cues, target)
            if not cues_aligned(source_cues, translated_cues):
                raise PipelineError("translation produced misaligned subtitle timings")
            write_srt(tmp_output, translated_cues)
            if not validate_srt(tmp_output):
                raise PipelineError("translation produced invalid SRT")

        self._run_logged(paths.translate_log, operation)
        _replace_file(tmp_output, paths.translated_srt)
        return self.translate_state(paths)

    def run_merge(
        self,
        project_id: str,
        target_language: str | None = None,
        force: bool = False,
    ) -> StepState:
        project = self.store.load(project_id)
        paths = ProjectPaths(project, target_language)
        state = self.merge_state(paths)
        if state.is_complete and not force:
            return state
        if not state.can_run:
            raise PipelineError(state.message)

        tmp_output = paths.tmp_dir / f"{paths.final_srt.name}.tmp"

        def operation() -> None:
            source_cues = read_srt(paths.source_srt)
            translated_cues = read_srt(paths.translated_srt)
            merged = merge_cues(source_cues, translated_cues)
            write_srt(tmp_output, merged)
            if not validate_srt(tmp_output):
                raise PipelineError("merge produced invalid SRT")

        self._run_logged(paths.merge_log, operation)
        _replace_file(tmp_output, paths.final_srt)
        return self.merge_state(paths)

    def run_all(
        self,
        project_id: str,
        target_language: str | None = None,
        force: bool = False,
    ) -> list[StepState]:
        states = [
            self.run_extract(project_id, force=force),
            self.run_transcribe(project_id, force=force),
            self.run_translate(project_id, target_language=target_language, force=force),
            self.run_merge(project_id, target_language=target_language, force=force),
        ]
        return states

    def _translated_output_valid(self, paths: ProjectPaths) -> bool:
        try:
            source_cues = read_srt(paths.source_srt)
            translated_cues = read_srt(paths.translated_srt)
        except Exception:
            return False
        return cues_aligned(source_cues, translated_cues)

    def _final_output_valid(self, paths: ProjectPaths) -> bool:
        try:
            source_cues = read_srt(paths.source_srt)
            final_cues = read_srt(paths.final_srt)
        except Exception:
            return False
        if len(source_cues) != len(final_cues):
            return False
        for source, final in zip(source_cues, final_cues):
            if abs(source.start_seconds - final.start_seconds) > 0.001:
                return False
            if abs(source.end_seconds - final.end_seconds) > 0.001:
                return False
        return True

    def _run_logged(self, log_path: Path, operation: Callable[[], None]) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("w", encoding="utf-8") as log_file:
                with redirect_stdout(log_file), redirect_stderr(log_file):
                    operation()
                    print("Step completed successfully.")
        except Exception as error:
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write("\nStep failed.\n")
                log_file.write(f"{type(error).__name__}: {error}\n")
                if isinstance(error, subprocess.CalledProcessError):
                    if error.stdout:
                        log_file.write("\nstdout:\n")
                        log_file.write(str(error.stdout))
                    if error.stderr:
                        log_file.write("\nstderr:\n")
                        log_file.write(str(error.stderr))
                log_file.write(traceback.format_exc())
            raise


def _replace_file(tmp_output: Path, final_output: Path) -> None:
    final_output.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_output, final_output)


def _require_nonempty_file(path: Path, message: str) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise PipelineError(message)
