from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import typer

from video_workflow.config import load_settings
from video_workflow.models import StepState
from video_workflow.pipeline import Pipeline, PipelineError
from video_workflow.projects import ProjectError, ProjectStore

app = typer.Typer(help="Local video subtitle workflow.")
projects_app = typer.Typer(help="Create and list projects.")
app.add_typer(projects_app, name="projects")


def _settings():
    return load_settings()


def _store() -> ProjectStore:
    return ProjectStore(_settings())


def _pipeline() -> Pipeline:
    settings = _settings()
    return Pipeline(settings, ProjectStore(settings))


@projects_app.command("list")
def list_projects() -> None:
    """List projects under the workspace directory."""
    try:
        projects = _store().list_projects()
    except ProjectError as error:
        raise typer.BadParameter(str(error)) from error

    if not projects:
        typer.echo("No projects found.")
        return
    for project in projects:
        typer.echo(project.id)


@projects_app.command("create")
def create_project(project_id: str) -> None:
    """Create a project folder contract under the workspace directory."""
    try:
        project = _store().create(project_id)
    except ProjectError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f"Created project: {project.id}")
    typer.echo(str(project.root))


@app.command("status")
def status(project_id: str, target: Optional[str] = typer.Option(None, "--target")) -> None:
    """Show pipeline status for a project."""
    try:
        states = _pipeline().status(project_id, target)
    except (ProjectError, PipelineError) as error:
        raise typer.BadParameter(str(error)) from error
    _print_states(states)


@app.command("extract")
def extract(project_id: str, force: bool = typer.Option(False, "--force")) -> None:
    """Extract MP3 audio from the staged source video."""
    _run_single(lambda pipeline: pipeline.run_extract(project_id, force=force))


@app.command("transcribe")
def transcribe(project_id: str, force: bool = typer.Option(False, "--force")) -> None:
    """Transcribe extracted audio into source-language SRT."""
    _run_single(lambda pipeline: pipeline.run_transcribe(project_id, force=force))


@app.command("translate")
def translate(
    project_id: str,
    target: Optional[str] = typer.Option(None, "--target"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Translate source-language SRT into target-language SRT."""
    _run_single(lambda pipeline: pipeline.run_translate(project_id, target, force=force))


@app.command("merge")
def merge(
    project_id: str,
    target: Optional[str] = typer.Option(None, "--target"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Merge source and translated subtitles into final bilingual SRT."""
    _run_single(lambda pipeline: pipeline.run_merge(project_id, target, force=force))


@app.command("run")
def run(
    project_id: str,
    target: Optional[str] = typer.Option(None, "--target"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Run all needed pipeline steps in order."""
    try:
        states = _pipeline().run_all(project_id, target, force=force)
    except (ProjectError, PipelineError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from error
    _print_states(states)


@app.command("web")
def web() -> None:
    """Start the local web app."""
    settings = _settings()
    try:
        import uvicorn
    except ImportError as error:
        raise typer.BadParameter("uvicorn is not installed.") from error

    from video_workflow.web.app import create_app

    uvicorn.run(
        create_app(settings),
        host=settings.web_host,
        port=settings.web_port,
        reload=False,
    )


def _run_single(operation) -> None:
    try:
        state = operation(_pipeline())
    except (ProjectError, PipelineError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from error
    _print_state(state)


def _print_states(states: list[StepState]) -> None:
    for state in states:
        _print_state(state)


def _print_state(state: StepState) -> None:
    outputs = ", ".join(str(path) for path in state.output_paths)
    typer.echo(f"{state.name.value}: {state.status.value} - {state.message}")
    typer.echo(f"  output: {outputs}")
    typer.echo(f"  log: {state.log_path}")
