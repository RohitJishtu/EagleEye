"""Tests for understand build workflow and storage."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx
from typer.testing import CliRunner

from eagleeye.main import app
from eagleeye.storage.maps import load_map, map_path, save_map

README = "# Demo Repo\n\nA sample data pipeline project.\n"


@pytest.fixture(autouse=True)
def _env_tokens(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("AUTH_MODE", "direct")


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


@respx.mock
def test_build_repo_map_detects_signals():
    owner, repo = "acme", "data-pipeline"

    from eagleeye.core.config import load_config
    from eagleeye.workflows.understand_build import build_repo_map

    respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=httpx.Response(200, json={
            "name": repo,
            "full_name": f"{owner}/{repo}",
            "description": "ETL pipelines",
            "language": "Python",
            "topics": ["data"],
            "default_branch": "main",
            "html_url": f"https://github.com/{owner}/{repo}",
        })
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/main").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "sha1"}})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/sha1").mock(
        return_value=httpx.Response(200, json={"tree": [
            {"path": "README.md", "type": "blob"},
            {"path": "pyproject.toml", "type": "blob"},
            {"path": "dbt_project.yml", "type": "blob"},
            {"path": ".github/workflows/ci.yml", "type": "blob"},
            {"path": "models/staging/users.sql", "type": "blob"},
            {"path": "dags/", "type": "tree"},
        ]})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/readme").mock(
        return_value=httpx.Response(200, text=README)
    )

    repo_map = build_repo_map(owner, repo, load_config())
    assert repo_map.owner == owner
    assert repo_map.repo == repo
    assert repo_map.file_count == 5
    assert "dbt" in repo_map.signals
    assert "github-actions" in repo_map.signals
    assert "python-packaging" in repo_map.signals
    assert README.strip() in repo_map.readme_excerpt
    assert "README.md" in repo_map.key_files


def test_save_and_load_map(tmp_path, monkeypatch):
    monkeypatch.setattr("eagleeye.storage.maps._MAPS_DIR", tmp_path)

    from eagleeye.core.models import RepoMap

    repo_map = RepoMap(
        owner="acme",
        repo="demo",
        branch="main",
        built_at="2026-07-08T00:00:00+00:00",
        description="test",
        signals=["dbt"],
    )
    path = save_map(repo_map)
    assert path == tmp_path / "acme__demo.json"
    loaded = load_map("acme", "demo")
    assert loaded is not None
    assert loaded.signals == ["dbt"]


@respx.mock
def test_understand_build_cli(tmp_path, monkeypatch):
    monkeypatch.setattr("eagleeye.storage.maps._MAPS_DIR", tmp_path)

    owner, repo = "acme", "demo"
    respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=httpx.Response(200, json={
            "name": repo,
            "description": "Demo",
            "language": "Python",
            "topics": [],
            "default_branch": "main",
            "html_url": f"https://github.com/{owner}/{repo}",
        })
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/main").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "sha1"}})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/sha1").mock(
        return_value=httpx.Response(200, json={"tree": [
            {"path": "README.md", "type": "blob"},
            {"path": "main.py", "type": "blob"},
        ]})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/readme").mock(
        return_value=httpx.Response(200, text=README)
    )

    runner = CliRunner()
    result = runner.invoke(app, ["understand", "build", f"{owner}/{repo}"])
    assert result.exit_code == 0, result.output
    assert map_path(owner, repo).exists()
    assert "Repo map saved" in result.output
