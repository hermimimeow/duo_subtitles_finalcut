from __future__ import annotations

import functools
import subprocess
from typing import Callable, NoReturn, Optional, TypeVar

import typer

from video_workflow.config import load_settings
from video_workflow.models import StepState
from video_workflow.pipeline import Pipeline, PipelineError
from video_workflow.projects import ProjectError, ProjectStore

app = typer.Typer(help="Local video subtitle workflow.")
projects_app = typer.Typer(help="Create and list projects.")
app.add_typer(projects_app, name="projects")

COMMAND_ERRORS = (ProjectError, PipelineError, RuntimeError, OSError, subprocess.SubprocessError)

CommandFunc = TypeVar("CommandFunc", bound=Callable[..., None])


def _fail(message: str) -> NoReturn:
    """Print an error message to stderr and exit with status 1."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(1)


def _reports_errors(command: CommandFunc) -> CommandFunc:
    """Decorator that prints known errors as a message and exits with status 1."""
    @functools.wraps(command)
    def wrapper(*args, **kwargs) -> None:
        try:
            command(*args, **kwargs)
        except COMMAND_ERRORS as error:
            _fail(str(error))

    return wrapper  # type: ignore[return-value]


def _store() -> ProjectStore:
    """Create a ProjectStore from the current settings."""
    return ProjectStore(load_settings())


def _pipeline() -> Pipeline:
    """Create a Pipeline from the current settings."""
    return Pipeline(load_settings())


@projects_app.command("list")
@_reports_errors
def list_projects() -> None:
    """List projects under the workspace directory."""
    projects = _store().list_projects()
    if not projects:
        typer.echo("No projects found.")
        return
    for project in projects:
        typer.echo(project.id)


@projects_app.command("create")
@_reports_errors
def create_project(project_id: str) -> None:
    """Create a project folder contract under the workspace directory."""
    project = _store().create(project_id)
    typer.echo(f"Created project: {project.id}")
    typer.echo(str(project.root))


@app.command("status")
@_reports_errors
def status(project_id: str, target: Optional[str] = typer.Option(None, "--target")) -> None:
    """Show pipeline status for a project."""
    _print_states(_pipeline().status(project_id, target))


@app.command("extract")
@_reports_errors
def extract(project_id: str, force: bool = typer.Option(False, "--force")) -> None:
    """Extract MP3 audio from the staged source video."""
    _print_state(_pipeline().run_extract(project_id, force=force))


@app.command("transcribe")
@_reports_errors
def transcribe(project_id: str, force: bool = typer.Option(False, "--force")) -> None:
    """Transcribe extracted audio into source-language SRT."""
    _print_state(_pipeline().run_transcribe(project_id, force=force))


@app.command("translate")
@_reports_errors
def translate(
    project_id: str,
    target: Optional[str] = typer.Option(None, "--target"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Translate source-language SRT into target-language SRT."""
    _print_state(_pipeline().run_translate(project_id, target, force=force))


@app.command("merge")
@_reports_errors
def merge(
    project_id: str,
    target: Optional[str] = typer.Option(None, "--target"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Merge source and translated subtitles into final bilingual SRT."""
    _print_state(_pipeline().run_merge(project_id, target, force=force))


@app.command("run")
@_reports_errors
def run(
    project_id: str,
    target: Optional[str] = typer.Option(None, "--target"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Run all needed pipeline steps in order."""
    _print_states(_pipeline().run_all(project_id, target, force=force))


@app.command("web")
def web() -> None:
    """Start the local web app."""
    settings = load_settings()
    try:
        import uvicorn
    except ImportError:
        _fail("uvicorn is not installed.")

    from video_workflow.web.app import create_app

    uvicorn.run(
        create_app(settings),
        host=settings.web_host,
        port=settings.web_port,
        reload=False,
    )


def _print_states(states: list[StepState]) -> None:
    """Print the status of each step."""
    for state in states:
        _print_state(state)


def _print_state(state: StepState) -> None:
    """Print one step's status, output path and log path."""
    outputs = ", ".join(str(path) for path in state.output_paths)
    typer.echo(f"{state.name.value}: {state.status.value} - {state.message}")
    typer.echo(f"  output: {outputs}")
    typer.echo(f"  log: {state.log_path}")
