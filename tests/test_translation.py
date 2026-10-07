import pytest

from video_workflow.models import SubtitleCue
from video_workflow.translation import TranslationError, apply_translation_payload


def test_apply_translation_payload_preserves_timings() -> None:
    cues = [SubtitleCue(1, 0.0, 1.0, "你好")]
    payload = {"translations": [{"index": 1, "text": "Hello"}]}

    translated = apply_translation_payload(cues, payload)

    assert translated == [SubtitleCue(1, 0.0, 1.0, "Hello")]


def test_apply_translation_payload_requires_all_rows() -> None:
    cues = [SubtitleCue(1, 0.0, 1.0, "你好")]

    with pytest.raises(TranslationError):
        apply_translation_payload(cues, {"translations": []})
