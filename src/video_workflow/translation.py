from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from video_workflow.config import Settings
from video_workflow.models import SubtitleCue

if TYPE_CHECKING:
    from google import genai


class TranslationError(RuntimeError):
    pass


TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["index", "text"],
            },
        }
    },
    "required": ["translations"],
}

DEFAULT_RETRY_DELAYS = (2.0, 4.0)


class GeminiTranslator:
    def __init__(
        self,
        settings: Settings,
        batch_size: int = 25,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.batch_size = max(batch_size, 1)
        self.retry_delays = retry_delays
        self.sleep = sleep

    def translate(self, cues: list[SubtitleCue], target_language: str) -> list[SubtitleCue]:
        if not cues:
            raise TranslationError("No source cues to translate")
        if not self.settings.gemini_api_key:
            raise TranslationError("GEMINI_API_KEY is required for translation")

        try:
            from google import genai
        except ImportError as error:
            raise TranslationError("google-genai is not installed.") from error

        client = genai.Client(api_key=self.settings.gemini_api_key)
        translated: list[SubtitleCue] = []
        for batch in _batch(cues, self.batch_size):
            translated.extend(self._translate_batch(client, batch, target_language))
        return translated

    def _translate_batch(
        self,
        client: genai.Client,
        cues: list[SubtitleCue],
        target_language: str,
    ) -> list[SubtitleCue]:
        response = self._generate_with_retries(client, cues, target_language)
        payload = response.parsed if getattr(response, "parsed", None) is not None else None
        if payload is None:
            payload = json.loads(getattr(response, "text", "") or "{}")
        return apply_translation_payload(cues, payload)

    def _generate_with_retries(
        self,
        client: genai.Client,
        cues: list[SubtitleCue],
        target_language: str,
    ):
        """Retry one batch on temporary Gemini errors; other batches are not affected."""
        attempts = len(self.retry_delays) + 1
        for attempt in range(1, attempts + 1):
            try:
                return client.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=build_translation_prompt(cues, target_language),
                    config={
                        "temperature": 0.25,
                        "response_mime_type": "application/json",
                        "response_json_schema": TRANSLATION_SCHEMA,
                    },
                )
            except Exception as error:
                if attempt == attempts or not _is_temporary(error):
                    raise
                delay = self.retry_delays[attempt - 1]
                print(
                    f"Gemini temporary error (attempt {attempt} of {attempts}), "
                    f"retrying in {delay:g}s: {error}"
                )
                self.sleep(delay)
        raise AssertionError("unreachable: the final attempt either returns or raises")


def build_translation_prompt(cues: list[SubtitleCue], target_language: str) -> str:
    rows = [
        {
            "index": cue.index,
            "text": cue.text,
        }
        for cue in cues
    ]
    return f"""
Translate these subtitle rows into {target_language}.

Rules:
- Preserve each input index exactly.
- Return one translated text value for every input row.
- Translate only the subtitle text.
- Do not add timestamps.
- Keep the wording concise and subtitle-readable.
- Preserve meaning and do not add facts.
- The source language is mostly Cantonese.

Rows:
{json.dumps(rows, ensure_ascii=False, indent=2)}
""".strip()


def apply_translation_payload(cues: list[SubtitleCue], payload: object) -> list[SubtitleCue]:
    if not isinstance(payload, dict):
        raise TranslationError("Gemini returned an invalid JSON object")
    translations = payload.get("translations")
    if not isinstance(translations, list):
        raise TranslationError("Gemini response did not include a translations list")

    by_index: dict[int, str] = {}
    for item in translations:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item["index"])
        except (KeyError, TypeError, ValueError):
            continue
        text = str(item.get("text") or "").strip()
        by_index[index] = text

    translated: list[SubtitleCue] = []
    missing: list[int] = []
    for cue in cues:
        text = by_index.get(cue.index, "").strip()
        if not text:
            missing.append(cue.index)
            continue
        translated.append(SubtitleCue(cue.index, cue.start_seconds, cue.end_seconds, text))

    if missing:
        raise TranslationError(f"Gemini response missed translation rows: {missing}")
    return translated


def _is_temporary(error: Exception) -> bool:
    """Server errors (503) and rate limits (429) are worth retrying."""
    try:
        from google.genai import errors
    except ImportError:
        return False
    if isinstance(error, errors.ServerError):
        return True
    return isinstance(error, errors.APIError) and getattr(error, "code", None) == 429


def _batch(cues: list[SubtitleCue], batch_size: int) -> list[list[SubtitleCue]]:
    return [cues[index : index + batch_size] for index in range(0, len(cues), batch_size)]
