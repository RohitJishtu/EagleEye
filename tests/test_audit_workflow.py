"""Tests for repo audit workflow and CLI."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from eagleeye.main import app

VULNERABLE_FILES = Path(__file__).parent / "fixtures" / "vulnerable_files"


@pytest.fixture(autouse=True)
def _env_tokens(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("AUTH_MODE", "direct")


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


@respx.mock
def test_run_repo_audit_finds_sql_injection():
    owner, repo = "acme", "pipelines"
    sql_content = (VULNERABLE_FILES / "instantiate_snowflake_tables.py").read_text()

    respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=httpx.Response(200, json={"default_branch": "main"})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/main").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "abc123"}})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/abc123").mock(
        return_value=httpx.Response(200, json={"tree": [
            {"path": "jobs/instantiate_snowflake_tables.py", "type": "blob"},
        ]})
    )
    respx.get(
        f"https://api.github.com/repos/{owner}/{repo}/contents/jobs/instantiate_snowflake_tables.py"
    ).mock(
        return_value=httpx.Response(200, json={
            "content": _b64(sql_content),
            "encoding": "base64",
        })
    )

    from eagleeye.core.config import load_config
    from eagleeye.workflows.repo_audit import run_repo_audit

    result, branch, files, coverage = run_repo_audit(owner, repo, load_config())
    assert branch == "main"
    assert files == ["jobs/instantiate_snowflake_tables.py"]
    assert coverage["audit_scanned"] >= 1
    assert result.critical_count >= 1
    assert any("injection" in f.title.lower() for f in result.findings)


@respx.mock
def test_audit_cli_json_output():
    owner, repo = "acme", "demo"
    respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=httpx.Response(200, json={"default_branch": "main"})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/main").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "abc123"}})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/abc123").mock(
        return_value=httpx.Response(200, json={"tree": [
            {"path": "app.py", "type": "blob"},
        ]})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/contents/app.py").mock(
        return_value=httpx.Response(200, json={
            "content": _b64('x = "safe code"\n'),
            "encoding": "base64",
        })
    )

    runner = CliRunner()
    result = runner.invoke(app, ["audit", f"{owner}/{repo}", "-o", "json"])
    assert result.exit_code == 0, result.output
    assert '"repo": "acme/demo"' in result.output
    assert '"files_checked": 1' in result.output
