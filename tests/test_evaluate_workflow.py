"""Tests for repo evaluation workflow."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from eagleeye.main import app
from eagleeye.workflows.repo_audit import select_priority_audit_paths

VULNERABLE_FILES = Path(__file__).parent / "fixtures" / "vulnerable_files"


@pytest.fixture(autouse=True)
def _env_tokens(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("AUTH_MODE", "direct")


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_priority_audit_prefers_config_over_data_json():
    """JiraAgent-like layout: config.yml must be scanned even with many data/*.json files."""
    tree = [{"path": f"data/issue_{i}.json", "type": "blob"} for i in range(55)]
    tree += [
        {"path": "config.yml", "type": "blob"},
        {"path": "main.py", "type": "blob"},
        {"path": "core/agent.py", "type": "blob"},
        {"path": "README.md", "type": "blob"},
    ]
    selected, coverage = select_priority_audit_paths(tree, key_paths=["README.md", "config.yml", "main.py"])
    assert "config.yml" in selected
    assert "main.py" in selected
    assert coverage.audit_eligible >= 58
    assert coverage.audit_scanned <= 60


@respx.mock
def test_evaluate_no_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("EAGLEEYE_EVALUATIONS_DIR", str(tmp_path))
    monkeypatch.setattr("eagleeye.storage.maps._MAPS_DIR", tmp_path / "maps")
    owner, repo = "acme", "jira-agent"

    respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=httpx.Response(200, json={
            "name": repo,
            "description": "Jira similarity app",
            "language": "Python",
            "topics": [],
            "default_branch": "main",
            "html_url": f"https://github.com/{owner}/{repo}",
        })
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/readme").mock(
        return_value=httpx.Response(200, text="# JiraAgent\nFind similar tickets.")
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/main").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "sha1"}})
    )

    tree_items = [{"path": f"data/{i}.json", "type": "blob"} for i in range(10)]
    tree_items += [
        {"path": "config.yml", "type": "blob"},
        {"path": "main.py", "type": "blob"},
        {"path": "README.md", "type": "blob"},
    ]
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/sha1").mock(
        return_value=httpx.Response(200, json={"tree": tree_items})
    )

    sql_content = (VULNERABLE_FILES / "instantiate_snowflake_tables.py").read_text()

    def content_route(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/contents/")[-1]
        if path == "config.yml":
            body = "jira_token: ghp_testplaceholder\n"
        elif path.endswith(".py"):
            body = sql_content if "main" in path else "x = 1\n"
        else:
            body = '{"issue": "test"}' if path.endswith(".json") else "# readme\n"
        return httpx.Response(200, json={"content": _b64(body), "encoding": "base64"})

    respx.route(
        method="GET",
        url=re.compile(rf"https://api\.github\.com/repos/{owner}/{repo}/contents/.*"),
    ).mock(side_effect=content_route)

    runner = CliRunner()
    result = runner.invoke(app, ["evaluate", f"{owner}/{repo}", "--no-llm"])
    assert result.exit_code == 0, result.output
    assert "Repo Evaluation" in result.output
    assert "Executive summary" in result.output
    assert list(tmp_path.glob("**/*.md"))
