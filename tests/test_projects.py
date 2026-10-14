from pathlib import Path

from video_workflow.config import Settings
from video_workflow.projects import ProjectPaths, ProjectStore


def test_create_project_generates_folder_contract(tmp_path: Path) -> None:
    store = ProjectStore(Settings(workspace_dir=tmp_path))

    project = store.create("project_1")
    paths = ProjectPaths(project)

    assert paths.metadata.exists()
    assert paths.video_dir.is_dir()
    assert paths.audio_dir.is_dir()
    assert paths.subtitles_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.tmp_dir.is_dir()
    assert paths.audio == tmp_path / "project_1" / "audio" / "project_1.mp3"
    assert paths.source_srt == tmp_path / "project_1" / "subtitles" / "project_1.yue.srt"
    assert paths.translated_srt == tmp_path / "project_1" / "subtitles" / "project_1.en.srt"
    assert paths.final_srt == tmp_path / "project_1" / "subtitles" / "project_1.en.final.srt"


def test_list_projects_loads_existing_project_folders(tmp_path: Path) -> None:
    store = ProjectStore(Settings(workspace_dir=tmp_path))
    store.create("project_1")
    store.create("project_2")

    projects = store.list_projects()

    assert [project.id for project in projects] == ["project_1", "project_2"]
