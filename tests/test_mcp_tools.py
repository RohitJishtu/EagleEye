"""MCP tool behavioral tests (mocked GitHub HTTP)."""

from __future__ import annotations

import os

import httpx
import pytest
import respx

from eagleeye.core.paths import reviews_dir


@pytest.fixture(autouse=True)
def _env_tokens(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("AUTH_MODE", "direct")


@pytest.fixture
def reviews_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("EAGLEEYE_REVIEWS_DIR", str(tmp_path))
    return tmp_path


@respx.mock
def test_list_pull_requests_parses_repo(reviews_tmp):
    owner, repo = "acme", "demo"
    route = respx.get(f"https://api.github.com/repos/{owner}/{repo}/pulls").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "number": 7,
                    "title": "Fix bug",
                    "user": {"login": "dev1"},
                    "updated_at": "2026-06-26T10:00:00Z",
                    "draft": False,
                    "html_url": f"https://github.com/{owner}/{repo}/pull/7",
                }
            ],
        )
    )

    from eagleeye.servers.mcp.tools.github import list_pull_requests

    out = list_pull_requests(f"{owner}/{repo}")
    assert route.called
    assert "PR #7" in out
    assert "Fix bug" in out


@respx.mock
def test_get_pull_request_returns_diff_and_metadata(reviews_tmp):
    owner, repo, pr = "acme", "demo", 3
    pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr}"

    respx.get(pr_url, headers={"Accept": "application/vnd.github.v3.diff"}).mock(
        return_value=httpx.Response(200, text="diff --git a/foo.py b/foo.py\n+print('hi')")
    )
    respx.get(pr_url, headers={"Accept": "application/vnd.github+json"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "number": pr,
                "title": "Add feature",
                "user": {"login": "dev2"},
                "base": {"ref": "main"},
                "head": {"sha": "abc123"},
                "body": "Test body",
                "html_url": f"https://github.com/{owner}/{repo}/pull/{pr}",
                "state": "open",
            },
        )
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr}/files").mock(
        return_value=httpx.Response(
            200,
            json=[{"filename": "foo.py", "status": "modified", "additions": 1, "deletions": 0}],
        )
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=httpx.Response(
            200,
            json={"default_branch": "main", "full_name": f"{owner}/{repo}"},
        )
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/contents/foo.py").mock(
        return_value=httpx.Response(
            200,
            json={"content": "cHJpbnQoJ2hpJyk=\n", "encoding": "base64"},
        )
    )

    from eagleeye.servers.mcp.tools.github import get_pull_request

    out = get_pull_request(f"{owner}/{repo}", pr)
    assert "Add feature" in out
    assert "foo.py" in out
    assert "diff --git" in out or "print" in out


def test_save_review_writes_markdown(reviews_tmp):
    from eagleeye.servers.mcp.tools.review import save_review

    repo = "acme/demo"
    msg = save_review(repo, 42, "Fix login bug", "## Summary\nLooks good.")
    out_dir = reviews_dir("acme", "demo")
    files = list(out_dir.glob("pr-42-*.md"))
    assert files, msg
    text = files[0].read_text()
    assert "repo: acme/demo" in text
    assert "Looks good." in text


def test_mcp_tools_registered():
    from eagleeye.servers.mcp.server import mcp

    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert "get_pull_request" in names
    assert "save_review" in names
    assert "list_pull_requests" in names
