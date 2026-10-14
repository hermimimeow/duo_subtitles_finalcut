from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from video_workflow.config import Settings, load_settings
from video_workflow.models import StepName
from video_workflow.pipeline import Pipeline
from video_workflow.projects import ProjectPaths, ProjectStore

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
TEXT_PREVIEW_CHARS = 12000


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = ProjectStore(settings)
    pipeline = Pipeline(settings, store)

    app = FastAPI(title="Video Workflow")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        projects = store.list_projects()
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "projects": projects,
                "workspace_dir": settings.workspace_dir,
                "error": None,
            },
        )

    @app.post("/projects")
    def create_project(project_id: str = Form(...)) -> RedirectResponse:
        project = store.create(project_id.strip())
        return RedirectResponse(f"/projects/{project.id}", status_code=303)

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project_detail(
        request: Request,
        project_id: str,
        target: str | None = None,
    ) -> HTMLResponse:
        context = _project_context(request, store, pipeline, project_id, target)
        context["error"] = None
        return templates.TemplateResponse(request, "project.html", context)

    @app.post("/projects/{project_id}/steps/{step_name}", response_class=HTMLResponse)
    def run_step(
        request: Request,
        project_id: str,
        step_name: StepName,
        target: str | None = Form(None),
        force: bool = Form(False),
    ) -> Response:
        step_runs: dict[StepName, Callable[[], object]] = {
            StepName.EXTRACT: lambda: pipeline.run_extract(project_id, force=force),
            StepName.TRANSCRIBE: lambda: pipeline.run_transcribe(project_id, force=force),
            StepName.TRANSLATE: lambda: pipeline.run_translate(project_id, target, force=force),
            StepName.MERGE: lambda: pipeline.run_merge(project_id, target, force=force),
        }
        return _run_and_render(
            request, store, pipeline, project_id, target, step_runs[step_name]
        )

    @app.post("/projects/{project_id}/run", response_class=HTMLResponse)
    def run_all(
        request: Request,
        project_id: str,
        target: str | None = Form(None),
        force: bool = Form(False),
    ) -> Response:
        return _run_and_render(
            request,
            store,
            pipeline,
            project_id,
            target,
            lambda: pipeline.run_all(project_id, target, force=force),
        )

    return app


def _run_and_render(
    request: Request,
    store: ProjectStore,
    pipeline: Pipeline,
    project_id: str,
    target: str | None,
    action: Callable[[], object],
) -> Response:
    error = None
    try:
        action()
    except Exception as exc:
        error = str(exc)

    context = _project_context(request, store, pipeline, project_id, target)
    context["error"] = error
    return _project_response(request, context)


def _project_context(
    request: Request,
    store: ProjectStore,
    pipeline: Pipeline,
    project_id: str,
    target: str | None,
) -> dict:
    project = store.load(project_id)
    effective_target = target or project.metadata.target_language
    paths = ProjectPaths(project, effective_target)
    return {
        "request": request,
        "project": project,
        "target": effective_target,
        "paths": paths,
        "states": pipeline.status(project_id, effective_target),
        "previews": _previews(paths),
    }


def _project_response(request: Request, context: dict) -> Response:
    template = "_project_body.html" if request.headers.get("HX-Request") == "true" else "project.html"
    return templates.TemplateResponse(request, template, context)


def _previews(paths: ProjectPaths) -> dict[str, str]:
    return {
        "video": _video_preview(paths),
        "audio": _file_summary(paths.audio),
        "source_srt": _text_preview(paths.source_srt),
        "translated_srt": _text_preview(paths.translated_srt),
        "final_srt": _text_preview(paths.final_srt),
        "extract_log": _text_preview(paths.extract_log),
        "transcribe_log": _text_preview(paths.transcribe_log),
        "translate_log": _text_preview(paths.translate_log),
        "merge_log": _text_preview(paths.merge_log),
    }


def _video_preview(paths: ProjectPaths) -> str:
    videos = (
        sorted(path.name for path in paths.video_dir.iterdir() if path.is_file())
        if paths.video_dir.is_dir()
        else []
    )
    return "\n".join(videos) if videos else "No video file staged."


def _file_summary(path: Path) -> str:
    if not path.exists():
        return "Missing."
    return f"{path.name}\n{path.stat().st_size} bytes"


def _text_preview(path: Path, max_chars: int = TEXT_PREVIEW_CHARS) -> str:
    if not path.exists():
        return "Missing."
    # Read one extra character so we know whether the file was longer than the limit
    # without loading the whole file.
    with path.open(encoding="utf-8", errors="replace") as file:
        text = file.read(max_chars + 1)
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text or "Empty file."
