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
    assert "EagleEye" in result.output
    assert "CRITICAL HITS" in result.output or "CRITICAL" in result.output
    assert "PLAN" in result.output
    assert list(tmp_path.glob("**/*.md"))


def test_format_evaluation_includes_modules_section():
    from eagleeye.core.models import ModuleReadResult, RemediationStep, RepoEvaluationResult
    from eagleeye.workflows.repo_evaluate.persist import format_evaluation_markdown

    result = RepoEvaluationResult(
        repo="acme/widget",
        branch="main",
        executive_summary="Summary",
        module_reads=[
            ModuleReadResult(
                module="core",
                purpose="Business logic and ingest",
                entry_points=["core/main.py"],
                data_stores=["sqlite"],
                files_read=["core/main.py", "core/ingest.py"],
            )
        ],
        remediation_plan=[
            RemediationStep(
                priority=1,
                severity="critical",
                title="Parameterize SQL",
                files=["core/ingest.py"],
                problem="f-string SQL",
                change_plan="Use bound parameters",
                acceptance_check="evaluate --no-llm clean",
            )
        ],
        coverage={"tree_files": 10, "audit_eligible": 8, "audit_scanned": 8,
                  "modules_planned": 1, "modules_read": 1, "files_deep_read": 2},
    )
    md = format_evaluation_markdown(result)
    assert "## Modules analyzed" in md
    assert "`core`" in md
    assert "Modules planned: 1" in md
    assert "Files deep-read: 2" in md
    assert "## Remediation plan" in md
    assert "Change plan:" in md
    assert "Acceptance check:" in md


def test_build_remediation_plan_from_findings():
    from eagleeye.core.models import EvalFinding
    from eagleeye.workflows.repo_evaluate.findings import build_remediation_plan

    plan = build_remediation_plan([
        EvalFinding(
            file="a.py",
            line=3,
            severity="critical",
            category="security",
            title="SQL injection",
            description="Dynamic SQL",
            fix="Use parameterized queries",
        ),
        EvalFinding(
            file="b.py",
            severity="high",
            category="secrets",
            title="Hardcoded token",
            description="Token in source",
            fix="Move to env var",
        ),
    ])
    assert len(plan) == 2
    assert plan[0].priority == 1
    assert plan[0].severity == "critical"
    assert "a.py" in plan[0].files
    assert "parameterized" in plan[0].change_plan.lower()
    assert plan[0].acceptance_check


@respx.mock
def test_evaluate_quick_skips_module_partition_path(tmp_path, monkeypatch):
    """--quick uses single-pass path; with --no-llm still succeeds without module LLM."""
    monkeypatch.setenv("EAGLEEYE_EVALUATIONS_DIR", str(tmp_path))
    monkeypatch.setattr("eagleeye.storage.maps._MAPS_DIR", tmp_path / "maps")
    owner, repo = "acme", "widget"

    respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=httpx.Response(200, json={
            "name": repo,
            "description": "Widget",
            "language": "Python",
            "topics": [],
            "default_branch": "main",
            "html_url": f"https://github.com/{owner}/{repo}",
        })
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/readme").mock(
        return_value=httpx.Response(200, text="# Widget\n")
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/main").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "sha1"}})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/sha1").mock(
        return_value=httpx.Response(200, json={"tree": [
            {"path": "core/a.py", "type": "blob"},
            {"path": "core/b.py", "type": "blob"},
            {"path": "main.py", "type": "blob"},
            {"path": "README.md", "type": "blob"},
        ]})
    )

    def content_route(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": _b64("x = 1\n"), "encoding": "base64"})

    respx.route(
        method="GET",
        url=re.compile(rf"https://api\.github\.com/repos/{owner}/{repo}/contents/.*"),
    ).mock(side_effect=content_route)

    runner = CliRunner()
    result = runner.invoke(app, ["evaluate", f"{owner}/{repo}", "--quick", "--no-llm"])
    assert result.exit_code == 0, result.output
    assert "EagleEye" in result.output
    assert "acme/widget" in result.output
