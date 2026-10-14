# Video Workflow

Local single-user video subtitle pipeline with CLI and web app control surfaces.

The app is designed around staged project folders. Each project contains one video and stores every pipeline output in predictable folders so individual steps can be restarted without rerunning the whole pipeline.

## Workflow

```text
workspace/project_1/video/project_1.mp4
  -> workspace/project_1/audio/project_1.mp3
  -> workspace/project_1/subtitles/project_1.yue.srt
  -> workspace/project_1/subtitles/project_1.en.srt
  -> workspace/project_1/subtitles/project_1.en.final.srt
```

Pipeline steps:

1. Extract audio from the source video into MP3.
2. Transcribe the audio with Whisper Large V3 and write timestamped Cantonese subtitles.
3. Translate the source subtitles with Gemini, defaulting to English.
4. Merge source and translated subtitles into one bilingual SRT.

## Project Structure

Recommended project folder:

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
    tmp/
```

The user stages the video manually by copying it into the project `video/` folder. The app owns generated files in `audio/`, `subtitles/`, `logs/`, and `tmp/`.

## Setup

```bash
uv sync --extra dev
cp .env.example .env
```

For transcription support, install the optional transcription dependency:

```bash
uv sync --extra dev --extra transcription
```

Add your Gemini API key to `.env` before running translation.

## CLI

```bash
uv run video-workflow projects list
uv run video-workflow projects create project_1
uv run video-workflow status project_1
uv run video-workflow extract project_1
uv run video-workflow transcribe project_1
uv run video-workflow translate project_1 --target en
uv run video-workflow merge project_1 --target en
uv run video-workflow run project_1 --target en
```

Default behavior:

- Reuse completed valid outputs.
- Run later steps without rerunning earlier completed steps.
- Require `--force` when intentionally overwriting an existing output from the CLI.
- Preserve the last known-good output if a rerun fails.

## Web App

The web app is a lightweight FastAPI/Jinja2/HTMX app, not Streamlit.

Start it with:

```bash
uv run video-workflow web
```

The app runs on `http://127.0.0.1:8000` by default and allows the user to:

- Select an existing project.
- Create a new project.
- Inspect staged files and logs.
- Run one pipeline step at a time.
- Run the full pipeline.
- Rerun completed steps from buttons.

## Configuration

Settings live in `.env`. A relative `WORKSPACE_DIR` is relative to the folder that contains `.env`, so the app finds the same workspace from any directory.

Expected settings:

```env
WORKSPACE_DIR=workspace
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
WHISPER_MODEL=large-v3
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=auto
WHISPER_LANGUAGE=
DEFAULT_SOURCE_LANGUAGE=yue
DEFAULT_TARGET_LANGUAGE=en
FFMPEG_BINARY=ffmpeg
WEB_HOST=127.0.0.1
WEB_PORT=8000
```

`GEMINI_API_KEY` is required for translation. FFmpeg is required for audio extraction.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Implementation Plan](docs/IMPLEMENTATION_PLAN.md)

## Tests

```bash
uv run pytest
```

## Current Status

Implemented:

- Python package scaffold.
- `.env` configuration loader.
- Project discovery and creation.
- Restartable pipeline status detection.
- FFmpeg audio extraction wrapper.
- faster-whisper transcription adapter.
- Gemini translation adapter.
- SRT parsing, rendering, validation, and merge.
- Typer CLI.
- FastAPI/Jinja2/HTMX web app.
- Unit tests for project paths, SRT behavior, translation payloads, and pipeline skip behavior.
