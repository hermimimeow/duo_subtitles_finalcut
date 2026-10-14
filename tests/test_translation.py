import pytest
from google.genai import errors

from video_workflow.config import Settings
from video_workflow.models import SubtitleCue
from video_workflow.translation import (
    GeminiTranslator,
    TranslationError,
    apply_translation_payload,
)


def test_apply_translation_payload_preserves_timings() -> None:
    cues = [SubtitleCue(1, 0.0, 1.0, "你好")]
    payload = {"translations": [{"index": 1, "text": "Hello"}]}

    translated = apply_translation_payload(cues, payload)

    assert translated == [SubtitleCue(1, 0.0, 1.0, "Hello")]


def test_apply_translation_payload_requires_all_rows() -> None:
    cues = [SubtitleCue(1, 0.0, 1.0, "你好")]

    with pytest.raises(TranslationError):
        apply_translation_payload(cues, {"translations": []})


class _Response:
    def __init__(self, payload: dict) -> None:
        self.parsed = payload


class _FakeModels:
    def __init__(self, outcomes: list) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, outcomes: list) -> None:
        self.models = _FakeModels(outcomes)


def _server_error() -> errors.ServerError:
    return errors.ServerError(
        503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}, None
    )


def _translator(sleeps: list[float]) -> GeminiTranslator:
    settings = Settings(gemini_api_key="test-key")
    return GeminiTranslator(settings, retry_delays=(2.0, 4.0), sleep=sleeps.append)


def _ok(index: int, text: str) -> _Response:
    return _Response({"translations": [{"index": index, "text": text}]})


def test_temporary_error_is_retried_then_succeeds() -> None:
    sleeps: list[float] = []
    client = _FakeClient([_server_error(), _ok(1, "Hello")])
    cues = [SubtitleCue(1, 0.0, 1.0, "你好")]

    translated = _translator(sleeps)._translate_batch(client, cues, "en")

    assert translated == [SubtitleCue(1, 0.0, 1.0, "Hello")]
    assert client.models.calls == 2
    assert sleeps == [2.0]


def test_other_errors_are_not_retried() -> None:
    sleeps: list[float] = []
    client = _FakeClient([ValueError("bad request")])
    cues = [SubtitleCue(1, 0.0, 1.0, "你好")]

    with pytest.raises(ValueError):
        _translator(sleeps)._translate_batch(client, cues, "en")

    assert client.models.calls == 1
    assert sleeps == []


def test_gives_up_after_last_retry() -> None:
    sleeps: list[float] = []
    client = _FakeClient([_server_error(), _server_error(), _server_error()])
    cues = [SubtitleCue(1, 0.0, 1.0, "你好")]

    with pytest.raises(errors.ServerError):
        _translator(sleeps)._translate_batch(client, cues, "en")

    assert client.models.calls == 3
    assert sleeps == [2.0, 4.0]


def test_retry_only_repeats_the_failing_batch() -> None:
    sleeps: list[float] = []
    # Batch 1 succeeds first try; batch 2 fails once, then succeeds.
    client = _FakeClient([_ok(1, "one"), _server_error(), _ok(2, "two")])
    cues = [SubtitleCue(1, 0.0, 1.0, "一"), SubtitleCue(2, 1.0, 2.0, "二")]
    translator = _translator(sleeps)

    translated = [
        cue
        for batch in ([cues[0]], [cues[1]])
        for cue in translator._translate_batch(client, batch, "en")
    ]

    assert [cue.text for cue in translated] == ["one", "two"]
    assert client.models.calls == 3
