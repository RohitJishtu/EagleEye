"""Tests for eagleeye.integrations.github.pr_fetch."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from eagleeye.integrations.github import pr_fetch
from eagleeye.integrations.github.pr_fetch import fetch_pr_data


def test_pr_fetch_module_imports():
    assert callable(pr_fetch.fetch_pr_data)
    assert callable(pr_fetch.fetch_file_contents)
    assert callable(pr_fetch.fetch_base_files_and_diff_symbols)
    assert callable(pr_fetch.fetch_cross_repo_callers)


@respx.mock
def test_fetch_pr_data_returns_diff_metadata_and_files():
    diff_text = "--- a/main.py\n+++ b/main.py\n@@ -1 +1,2 @@\n+pass\n"
    pr_payload = {
        "title": "Add pass",
        "user": {"login": "alice"},
        "base": {"ref": "main", "sha": "base123"},
        "head": {"sha": "head456"},
        "body": "Small change",
        "html_url": "https://github.com/owner/repo/pull/7",
        "number": 7,
        "state": "open",
        "merged_at": None,
    }
    files = [{"filename": "main.py", "additions": 1, "deletions": 0, "patch": "+pass"}]

    respx.get("https://api.github.com/repos/owner/repo/pulls/7").mock(
        side_effect=[
            httpx.Response(200, text=diff_text),
            httpx.Response(200, json=pr_payload),
        ]
    )
    respx.get("https://api.github.com/repos/owner/repo/pulls/7/files").mock(
        return_value=httpx.Response(200, json=files)
    )

    state = {
        "owner": "owner",
        "repo": "repo",
        "pr_number": 7,
        "github_token": "ghp_test",
    }
    result = fetch_pr_data(state)

    assert result["diff"] == diff_text
    assert result["pr_metadata"]["title"] == "Add pass"
    assert result["pr_metadata"]["author"] == "alice"
    assert result["file_list"] == ["main.py"]


@respx.mock
def test_fetch_file_contents_reads_head_files(monkeypatch):
    monkeypatch.setenv("EAGLEEYE_STRUCTURAL_DIFF", "0")

    content_b64 = base64.b64encode(b"print('hello')\n").decode()
    respx.get("https://api.github.com/repos/acme/app").mock(
        return_value=httpx.Response(200, json={"default_branch": "main"})
    )
    respx.get("https://api.github.com/repos/acme/app/contents/src/app.py").mock(
        return_value=httpx.Response(
            200,
            json={"encoding": "base64", "content": content_b64 + "\n"},
        )
    )

    state = {
        "owner": "acme",
        "repo": "app",
        "github_token": "ghp_test",
        "pr_metadata": {"head_sha": "abc123", "base": "main"},
        "file_list": ["src/app.py"],
        "max_files": 30,
        "max_file_bytes": 10_000,
        "max_total_bytes": 150_000,
    }
    result = pr_fetch.fetch_file_contents(state)

    assert result["files_total"] == 1
    assert result["files_fetched"] == 1
    assert "print('hello')" in result["full_file_contents"]["src/app.py"]
    assert result["file_manifest"][0]["status"] == "ok"
