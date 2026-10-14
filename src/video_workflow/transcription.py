from __future__ import annotations

from pathlib import Path

from video_workflow.config import Settings
from video_workflow.models import SubtitleCue


class TranscriptionError(RuntimeError):
    """Raised when transcription cannot run or produces no subtitle cues."""
    pass


class FasterWhisperTranscriber:
    """Turn an audio file into timed subtitle cues with faster-whisper."""
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe(self, audio_path: Path) -> list[SubtitleCue]:
        """Transcribe audio_path and return one cue per speech segment.

        Raises TranscriptionError if faster-whisper is missing or no speech is found.
        """
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)

        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise TranscriptionError(
                "faster-whisper is not installed. Install the transcription extra before transcribing."
            ) from error

        device = None if self.settings.whisper_device == "auto" else self.settings.whisper_device
        compute_type = (
            None
            if self.settings.whisper_compute_type == "auto"
            else self.settings.whisper_compute_type
        )
        model_kwargs: dict[str, str] = {}
        if device:
            model_kwargs["device"] = device
        if compute_type:
            model_kwargs["compute_type"] = compute_type

        model = WhisperModel(self.settings.whisper_model, **model_kwargs)
        segments, _info = model.transcribe(
            str(audio_path),
            language=self.settings.whisper_language,
            vad_filter=True,
        )

        cues: list[SubtitleCue] = []
        for index, segment in enumerate(segments, start=1):
            text = str(segment.text).strip()
            if not text:
                continue
            start_seconds = max(float(segment.start), 0.0)
            end_seconds = max(float(segment.end), start_seconds + 0.1)
            cues.append(SubtitleCue(index, start_seconds, end_seconds, text))
        if not cues:
            raise TranscriptionError("Transcription produced no subtitle cues")
        return cues
