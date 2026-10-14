from __future__ import annotations

import os
import subprocess
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from video_workflow.audio import extract_audio
from video_workflow.config import Settings
from video_workflow.models import StepName, StepState, StepStatus
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


@dataclass(frozen=True)
class _StepMessages:
    complete: str
    missing: str
    invalid: str
    ready: str


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
            self.extract_state(paths),
            self.transcribe_state(paths),
            self.translate_state(paths),
            self.merge_state(paths),
        ]

    def extract_state(self, paths: ProjectPaths) -> StepState:
        source_video: Path | None = None
        error_message = ""
        try:
            source_video = self.store.find_source_video(paths.project)
        except Exception as error:
            error_message = str(error)

        return _step_state(
            StepName.EXTRACT,
            input_paths=() if source_video is None else (source_video,),
            output_paths=(paths.audio,),
            log_path=paths.extract_log,
            output_valid=_is_nonempty_file(paths.audio),
            inputs_valid=source_video is not None,
            output_exists=paths.audio.exists(),
            messages=_StepMessages(
                complete=f"Audio exists: {paths.audio.name}",
                missing=error_message,
                invalid=f"Audio exists but is invalid: {paths.audio.name}",
                ready="" if source_video is None else f"Ready to extract from {source_video.name}",
            ),
        )

    def transcribe_state(self, paths: ProjectPaths) -> StepState:
        return _step_state(
            StepName.TRANSCRIBE,
            input_paths=(paths.audio,),
            output_paths=(paths.source_srt,),
            log_path=paths.transcribe_log,
            output_valid=validate_srt(paths.source_srt),
            inputs_valid=_is_nonempty_file(paths.audio),
            output_exists=paths.source_srt.exists(),
            messages=_StepMessages(
                complete=f"Source subtitles exist: {paths.source_srt.name}",
                missing=f"Missing audio: {paths.audio.name}",
                invalid=f"Source subtitle exists but is invalid: {paths.source_srt.name}",
                ready="Ready to transcribe",
            ),
        )

    def translate_state(self, paths: ProjectPaths) -> StepState:
        return _step_state(
            StepName.TRANSLATE,
            input_paths=(paths.source_srt,),
            output_paths=(paths.translated_srt,),
            log_path=paths.translate_log,
            output_valid=paths.translated_srt.exists() and self._translated_output_valid(paths),
            inputs_valid=validate_srt(paths.source_srt),
            output_exists=paths.translated_srt.exists(),
            messages=_StepMessages(
                complete=f"Translated subtitles exist: {paths.translated_srt.name}",
                missing=f"Missing valid source subtitles: {paths.source_srt.name}",
                invalid=f"Translated subtitle exists but is invalid: {paths.translated_srt.name}",
                ready="Ready to translate",
            ),
        )

    def merge_state(self, paths: ProjectPaths) -> StepState:
        inputs_valid = validate_srt(paths.source_srt) and self._translated_output_valid(paths)
        # A final file that is valid on its own still counts as complete when the
        # inputs are gone; only check alignment against the inputs when they exist.
        output_valid = validate_srt(paths.final_srt) and (
            not inputs_valid or self._final_output_valid(paths)
        )
        return _step_state(
            StepName.MERGE,
            input_paths=(paths.source_srt, paths.translated_srt),
            output_paths=(paths.final_srt,),
            log_path=paths.merge_log,
            output_valid=output_valid,
            inputs_valid=inputs_valid,
            output_exists=paths.final_srt.exists(),
            messages=_StepMessages(
                complete=f"Final subtitles exist: {paths.final_srt.name}",
                missing="Missing valid source or translated subtitles",
                invalid=f"Final subtitle exists but is invalid: {paths.final_srt.name}",
                ready="Ready to merge",
            ),
        )

    def run_extract(self, project_id: str, force: bool = False) -> StepState:
        return self._run_step(
            project_id,
            None,
            force,
            state_for=self.extract_state,
            operation=self._extract_audio,
        )

    def run_transcribe(self, project_id: str, force: bool = False) -> StepState:
        return self._run_step(
            project_id,
            None,
            force,
            state_for=self.transcribe_state,
            operation=self._transcribe_audio,
        )

    def run_translate(
        self,
        project_id: str,
        target_language: str | None = None,
        force: bool = False,
    ) -> StepState:
        return self._run_step(
            project_id,
            target_language,
            force,
            state_for=self.translate_state,
            operation=self._translate_subtitles,
        )

    def run_merge(
        self,
        project_id: str,
        target_language: str | None = None,
        force: bool = False,
    ) -> StepState:
        return self._run_step(
            project_id,
            target_language,
            force,
            state_for=self.merge_state,
            operation=self._merge_subtitles,
        )

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

    def _run_step(
        self,
        project_id: str,
        target_language: str | None,
        force: bool,
        *,
        state_for: Callable[[ProjectPaths], StepState],
        operation: Callable[[StepState, ProjectPaths, Path], None],
    ) -> StepState:
        project = self.store.load(project_id)
        paths = ProjectPaths(project, target_language)
        state = state_for(paths)
        if state.is_complete and not force:
            return state
        if not state.can_run:
            raise PipelineError(state.message)

        output = state.output_paths[0]
        tmp_output = paths.tmp_dir / f"{output.name}.tmp"
        self._run_logged(state.log_path, lambda: operation(state, paths, tmp_output))
        _replace_file(tmp_output, output)
        return state_for(paths)

    def _extract_audio(self, state: StepState, paths: ProjectPaths, tmp_output: Path) -> None:
        source_video = state.input_paths[0]
        result = extract_audio(source_video, tmp_output, self.settings.ffmpeg_binary)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        _require_nonempty_file(tmp_output, "audio extraction produced an empty file")

    def _transcribe_audio(self, state: StepState, paths: ProjectPaths, tmp_output: Path) -> None:
        cues = self.transcriber_factory(self.settings).transcribe(paths.audio)
        write_srt(tmp_output, cues)
        if not validate_srt(tmp_output):
            raise PipelineError("transcription produced invalid SRT")

    def _translate_subtitles(self, state: StepState, paths: ProjectPaths, tmp_output: Path) -> None:
        source_cues = read_srt(paths.source_srt)
        translated_cues = self.translator_factory(self.settings).translate(
            source_cues, paths.target_language
        )
        if not cues_aligned(source_cues, translated_cues):
            raise PipelineError("translation produced misaligned subtitle timings")
        write_srt(tmp_output, translated_cues)
        if not validate_srt(tmp_output):
            raise PipelineError("translation produced invalid SRT")

    def _merge_subtitles(self, state: StepState, paths: ProjectPaths, tmp_output: Path) -> None:
        source_cues = read_srt(paths.source_srt)
        translated_cues = read_srt(paths.translated_srt)
        merged = merge_cues(source_cues, translated_cues)
        write_srt(tmp_output, merged)
        if not validate_srt(tmp_output):
            raise PipelineError("merge produced invalid SRT")

    def _translated_output_valid(self, paths: ProjectPaths) -> bool:
        return _files_aligned(paths.source_srt, paths.translated_srt)

    def _final_output_valid(self, paths: ProjectPaths) -> bool:
        return _files_aligned(paths.source_srt, paths.final_srt)

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


def _step_state(
    name: StepName,
    *,
    input_paths: tuple[Path, ...],
    output_paths: tuple[Path, ...],
    log_path: Path,
    output_valid: bool,
    inputs_valid: bool,
    output_exists: bool,
    messages: _StepMessages,
) -> StepState:
    if output_valid:
        status, can_run, message = StepStatus.COMPLETE, True, messages.complete
    elif not inputs_valid:
        status, can_run, message = StepStatus.MISSING_INPUT, False, messages.missing
    elif output_exists:
        status, can_run, message = StepStatus.INVALID, True, messages.invalid
    else:
        status, can_run, message = StepStatus.READY, True, messages.ready

    return StepState(
        name=name,
        status=status,
        input_paths=input_paths,
        output_paths=output_paths,
        log_path=log_path,
        can_run=can_run,
        can_rerun=output_valid,
        message=message,
    )


def _is_nonempty_file(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _files_aligned(source_path: Path, other_path: Path) -> bool:
    try:
        source_cues = read_srt(source_path)
        other_cues = read_srt(other_path)
    except Exception:
        return False
    return cues_aligned(source_cues, other_cues)


def _replace_file(tmp_output: Path, final_output: Path) -> None:
    final_output.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_output, final_output)


def _require_nonempty_file(path: Path, message: str) -> None:
    if not _is_nonempty_file(path):
        raise PipelineError(message)
