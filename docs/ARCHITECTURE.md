# Architecture

## Overview

Video Workflow is a local, single-user video processing application. It provides a CLI and a lightweight web UI over the same Python pipeline core.

The application is organized around restartable file stages. Each project is a folder inside `workspace/`, and each pipeline step writes its result into a predictable subfolder. This makes the workflow easy to inspect, rerun, and recover without a database.

```text
Video file
  -> extract audio
  -> transcribe source subtitles
  -> translate subtitles
  -> merge bilingual subtitles
```

## Design Principles

- Single user, local first.
- Filesystem state is the source of truth.
- CLI and web UI share the same pipeline code.
- Each step is independently runnable.
- Completed valid artifacts are reused.
- Failed runs do not overwrite previous successful outputs.
- Configuration lives in `.env`; project state lives with the project folder.

## Runtime Surfaces

### CLI

The CLI is intended for direct, scriptable execution.

Example commands:

```bash
video-workflow status project_1
video-workflow extract project_1
video-workflow transcribe project_1
video-workflow translate project_1 --target en
video-workflow merge project_1 --target en
video-workflow run project_1 --target en
```

### Web App

The web app is intended for interactive local use.

It should allow the user to:

- Select an existing project.
- Create a new project folder.
- Inspect staged input and output files.
- Run one step at a time.
- Run the full pipeline.
- Rerun a previous step.
- View per-step logs.

Recommended implementation:

- FastAPI for HTTP routes.
- Jinja2 for templates.
- HTMX for button-triggered step execution and partial refresh.
- Static CSS and minimal JavaScript only where needed.

## Project Layout

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
      project_1.final.srt
    logs/
      extract-audio.log
      transcribe.log
      translate-en.log
      merge.log
    tmp/
```

### Folder Responsibilities

| Folder | Purpose |
|---|---|
| `video/` | User-staged source video file. |
| `audio/` | Extracted audio artifacts. |
| `subtitles/` | Source, translated, and final subtitle files. |
| `logs/` | Human-readable logs for each pipeline step. |
| `tmp/` | Partial files and temporary outputs during active step execution. |

### Project Metadata

`project.json` stores durable project metadata that should not live in `.env`.

Example:

```json
{
  "id": "project_1",
  "source_video": "video/project_1.mp4",
  "source_language": "yue",
  "target_language": "en",
  "created_at": "2026-06-08T00:00:00Z",
  "updated_at": "2026-06-08T00:00:00Z"
}
```

The application may generate this file lazily for existing folders.

## Configuration

Global settings are loaded from `.env`.

```env
WORKSPACE_DIR=workspace
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
WHISPER_MODEL=large-v3
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=auto
DEFAULT_SOURCE_LANGUAGE=yue
DEFAULT_TARGET_LANGUAGE=en
FFMPEG_BINARY=ffmpeg
WEB_HOST=127.0.0.1
WEB_PORT=8000
```

Configuration should be read once by the application boundary and passed into pipeline services. Pipeline modules should not directly read environment variables unless they are the configuration module.

## Core Modules

```text
src/video_workflow/
  config.py         Loads .env settings.
  models.py         Shared dataclasses and enums.
  projects.py       Project discovery, creation, and metadata.
  pipeline.py       Step orchestration and status detection.
  audio.py          FFmpeg command construction and execution.
  transcription.py  Whisper transcription adapter.
  translation.py    Gemini translation adapter.
  subtitles.py      SRT parse, render, validate, and merge.
  cli.py            Typer CLI.
  web/app.py        FastAPI app and routes.
```

## Pipeline Steps

### Step 1: Extract Audio

Input:

- One supported video file in `video/`.

Output:

- `audio/{project_id}.mp3`

Behavior:

- Use FFmpeg to extract mono 16 kHz MP3 audio.
- Write the result through `tmp/`.
- Validate output exists and is non-empty.
- Write `logs/extract-audio.log`.

### Step 2: Transcribe Source Subtitles

Input:

- `audio/{project_id}.mp3`

Output:

- `subtitles/{project_id}.yue.srt`

Behavior:

- Use Whisper Large V3 by default.
- Preserve segment timestamps.
- Render source-language SRT.
- Validate the SRT contains parseable cues.
- Write `logs/transcribe.log`.

### Step 3: Translate Subtitles

Input:

- `subtitles/{project_id}.yue.srt`

Output:

- `subtitles/{project_id}.en.srt`

Behavior:

- Parse source SRT into cues.
- Send text and cue indexes to Gemini in batches.
- Preserve timings exactly.
- Render translated SRT.
- Validate cue count and timestamp alignment.
- Write `logs/translate-en.log`.

### Step 4: Merge Subtitles

Input:

- `subtitles/{project_id}.yue.srt`
- `subtitles/{project_id}.en.srt`

Output:

- `subtitles/{project_id}.final.srt`

Behavior:

- Parse both SRT files.
- Confirm cue counts and timings match.
- Render one bilingual SRT cue per source cue.
- Default line order is source first, translation second.
- Write `logs/merge.log`.

## Step State Model

Each step should expose a status object:

```text
name
status: missing_input | ready | complete | invalid | failed
input_paths
output_paths
log_path
can_run
can_rerun
message
```

Status detection should validate outputs enough to avoid treating partial files as complete.

## Atomic Writes

Pipeline steps should not write directly to final artifact paths.

Recommended flow:

1. Create a temporary output path under `tmp/`.
2. Run the step and write the temporary file.
3. Validate the temporary file.
4. Rename it into the final destination.
5. Leave previous successful outputs untouched if validation fails.

## Error Handling

- Missing required input should produce a clear user-facing message.
- Ambiguous video input should ask the user to choose or update `project.json`.
- Provider errors should be logged with enough detail to diagnose.
- Secrets must not be written to logs.
- A failed step should mark only that step as failed.

## Web Execution Model

The first implementation can run web-triggered steps synchronously. This is simpler and acceptable for a single-user local app.

If long requests become painful, add an in-process job registry:

```text
job_id
project_id
step
status
started_at
ended_at
log_path
error
```

This does not require multi-user support or a database.

## Security Model

The app is intended to bind to localhost only.

- Default host: `127.0.0.1`.
- No authentication.
- No multi-user authorization.
- No arbitrary filesystem browsing outside `WORKSPACE_DIR`.
- Gemini receives subtitle text, not audio/video files.

## Prototype Reference

The existing `../VideoSubtitles` prototype is useful as a reference for:

- FFmpeg audio extraction.
- faster-whisper transcription wrapping.
- Gemini batch translation concepts.
- SRT rendering.

The new application should not copy the Streamlit UI structure. The reusable design is the separation between core processing modules and the UI surface.
