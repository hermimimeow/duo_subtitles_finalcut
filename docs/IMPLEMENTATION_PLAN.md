# Implementation Plan

## Goal

Build a local, single-user video subtitle pipeline with two control surfaces:

- A CLI for running individual pipeline steps or the whole pipeline.
- A lightweight Python web app for selecting projects, inspecting staged outputs, and rerunning steps.

The application processes one video per project folder under `workspace/`. Each step writes its output to a stable folder so later steps can be rerun without repeating earlier work.

## Scope

### In Scope

- Local project discovery and creation under `workspace/`.
- Audio extraction from local video files into MP3.
- Cantonese transcription with timestamps using Whisper Large V3 through a local Python-compatible engine.
- Subtitle translation with Gemini, defaulting to English.
- Merging source and translated subtitles into one bilingual SRT.
- Restartable step execution through CLI and web UI.
- Output preview in the web UI by reading staged files from each project folder.
- `.env` based settings.

### Out of Scope

- Multi-user accounts, authentication, permissions, and sharing.
- Cloud file storage.
- Database-backed project state.
- Browser-based video upload as the primary workflow.
- Streamlit.
- Final Cut Pro XML export unless added as a later phase.

## Proposed Stack

- Python 3.11 or newer.
- `uv` for local dependency and command management.
- FastAPI for the local web server.
- Jinja2 templates for server-rendered pages.
- HTMX for lightweight step execution and partial page refresh.
- Typer for CLI commands.
- python-dotenv or pydantic-settings for `.env` loading.
- FFmpeg for audio extraction.
- faster-whisper for local Whisper transcription.
- google-genai for Gemini translation.
- srt or pysrt for robust SRT parsing and rendering.
- pytest for unit tests.

## Repository Layout

```text
.
  README.md
  .env.example
  docs/
    ARCHITECTURE.md
    IMPLEMENTATION_PLAN.md
  src/
    video_workflow/
      __init__.py
      __main__.py
      audio.py
      cli.py
      config.py
      models.py
      pipeline.py
      projects.py
      subtitles.py
      transcription.py
      translation.py
      web/
        __init__.py
        app.py
        templates/
        static/
  tests/
  workspace/
    project_1/
      project.json
      video/
      audio/
      subtitles/
      logs/
      tmp/
```

## Project Folder Contract

Each project is one directory under `workspace/`.

```text
workspace/
  project_1/
    project.json
    video/
      project_1.mp4
    audio/
      project_1.mp3
    subtitles/
      project_1.yue.srt
      project_1.en.srt
      project_1.en.final.srt
    logs/
      extract-audio.log
      transcribe.log
      translate-en.log
      merge-en.log
    tmp/
```

### Naming Rules

- Project id is the folder name, for example `project_1`.
- Source video is placed by the user in `video/`.
- Extracted audio path is `audio/{project_id}.mp3`.
- Source subtitle path is `subtitles/{project_id}.{source_language}.srt`.
- Translated subtitle path is `subtitles/{project_id}.{target_language}.srt`.
- Final merged subtitle path is `subtitles/{project_id}.{target_language}.final.srt`.

Default languages:

- Source file language code: `yue`.
- Target language code: `en`.

The transcription engine language parameter should be configurable separately from the filename language code because model language identifiers may not exactly match `yue`.

## Phase 1: Project Foundation

1. Add Python package scaffold under `src/video_workflow`.
2. Add `pyproject.toml` with dependencies and command entry points.
3. Add `.env.example`.
4. Implement configuration loading:
   - `WORKSPACE_DIR`
   - `GEMINI_API_KEY`
   - `GEMINI_MODEL`
   - `WHISPER_MODEL`
   - `WHISPER_DEVICE`
   - `WHISPER_COMPUTE_TYPE`
   - `DEFAULT_SOURCE_LANGUAGE`
   - `DEFAULT_TARGET_LANGUAGE`
   - `FFMPEG_BINARY`
5. Implement project discovery and project creation.
6. Add unit tests for path generation and project discovery.

Deliverable:

- `uv run video-workflow projects list`
- `uv run video-workflow projects create project_1`

## Phase 2: Pipeline Core

1. Implement `ProjectPaths` to centralize all staged artifact paths.
2. Implement step status detection:
   - Missing input.
   - Ready to run.
   - Complete.
   - Failed or invalid output.
3. Implement atomic output writes:
   - Write to `tmp/`.
   - Validate output.
   - Rename into final location.
4. Implement log capture per step under `logs/`.
5. Add `--force` behavior for reruns.

Deliverable:

- A pipeline service that can answer which steps are complete and which can run next.

## Phase 3: Audio Extraction

1. Detect the source video file in `video/`.
2. Reject ambiguous projects with more than one supported video unless `project.json` selects one.
3. Run FFmpeg:

```bash
ffmpeg -y -i input.mp4 -vn -ac 1 -ar 16000 -b:a 64k output.mp3
```

4. Validate the generated MP3 exists and is non-empty.
5. Write `logs/extract-audio.log`.

Deliverable:

- `uv run video-workflow extract project_1`

## Phase 4: Transcription

1. Load extracted audio from `audio/{project_id}.mp3`.
2. Run faster-whisper with the configured Whisper model, defaulting to `large-v3`.
3. Use Cantonese-oriented configuration where supported by the backend.
4. Convert segments into SRT cues with exact timestamps.
5. Write `subtitles/{project_id}.yue.srt`.
6. Validate by parsing the generated SRT and checking at least one cue exists.

Deliverable:

- `uv run video-workflow transcribe project_1`

## Phase 5: Translation

1. Parse `subtitles/{project_id}.yue.srt`.
2. Batch subtitle rows for Gemini.
3. Ask Gemini to preserve cue indexes and timing while translating only text.
4. Default target language to English.
5. Write `subtitles/{project_id}.en.srt`.
6. Validate cue count and timing alignment against source SRT.

Deliverable:

- `uv run video-workflow translate project_1 --target en`

## Phase 6: Subtitle Merge

1. Parse source and translated SRT files.
2. Confirm cue counts and timestamp alignment.
3. Render a final bilingual SRT where each cue contains both languages.
4. Default line order:
   - Cantonese source.
   - English translation.
5. Write `subtitles/{project_id}.{target_language}.final.srt`.

Deliverable:

- `uv run video-workflow merge project_1 --target en`

## Phase 7: Full CLI

Implement commands:

```bash
video-workflow projects list
video-workflow projects create PROJECT_ID
video-workflow status PROJECT_ID
video-workflow extract PROJECT_ID
video-workflow transcribe PROJECT_ID
video-workflow translate PROJECT_ID --target en
video-workflow merge PROJECT_ID --target en
video-workflow run PROJECT_ID --target en
```

Rules:

- By default, skip completed valid steps.
- `--force` reruns the selected command and overwrites its final artifact.
- `run` executes only the needed incomplete steps in dependency order.
- Later steps fail with a clear message if required earlier artifacts are missing or invalid.

## Phase 8: Web App

1. Add FastAPI app.
2. Add project list page:
   - Existing projects.
   - Create project form.
3. Add project detail page:
   - Step status summary.
   - Buttons for each step.
   - Button for full pipeline.
   - Preview panels for video filename, audio metadata, source SRT, translated SRT, final SRT, and logs.
4. Use HTMX endpoints for running steps and refreshing the status/output panels.
5. Keep execution synchronous for the first version. Add background tasks only if needed after the core flow works.

Deliverable:

- `uv run video-workflow web`
- Local app opens at `http://127.0.0.1:8000`.

## Phase 9: Testing

Unit tests:

- Path generation.
- Project creation.
- Step status detection.
- SRT parsing/rendering.
- Merge behavior.
- Translation payload validation.

Integration tests:

- Audio extraction command construction.
- Pipeline skip behavior.
- CLI command behavior with temporary workspace fixtures.

Manual tests:

- Add a sample MP4 to `workspace/project_1/video/`.
- Run each CLI step independently.
- Run the full CLI pipeline after deleting only later artifacts.
- Inspect and rerun steps through the web UI.

## Restartability Rules

- Each step reads only from previous staged artifacts.
- Each step writes only its own staged artifact and log file.
- Existing valid outputs are reused.
- Invalid or partial outputs are not treated as complete.
- Reruns require `--force` in CLI or a clear rerun action in the web UI.
- A failed step must leave the last known-good artifact untouched.

## Open Decisions

- Whether to use `faster-whisper` exclusively or leave room for whisper.cpp as a second backend.
- Exact Whisper language parameter for Cantonese transcription.
- Whether web-triggered long-running steps should be synchronous initially or immediately use a background job registry.
- Resolved: `project.json` is written when a project is created. Opening a project without one uses in-memory defaults and writes nothing.
