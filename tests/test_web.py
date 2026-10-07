from pathlib import Path

from fastapi.testclient import TestClient

from video_workflow.config import Settings
from video_workflow.projects import ProjectStore
from video_workflow.web.app import create_app


def test_step_post_without_htmx_returns_full_page(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    ProjectStore(Settings(workspace_dir=tmp_path)).create("project_1")
    client = TestClient(create_app())

    response = client.post("/projects/project_1/steps/extract", data={"target": "en"})

    assert response.status_code == 200
    assert "<!doctype html>" in response.text
    assert 'id="project-body"' in response.text
    assert "No supported video file found" in response.text


def test_step_post_with_htmx_returns_project_body_fragment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    ProjectStore(Settings(workspace_dir=tmp_path)).create("project_1")
    client = TestClient(create_app())

    response = client.post(
        "/projects/project_1/steps/extract",
        data={"target": "en"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "<!doctype html>" not in response.text
    assert response.text.count('id="project-body"') == 1
    assert response.text.rstrip().endswith("</div>")
    assert "Extract Log" in response.text
