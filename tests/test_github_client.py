"""Tests for eagleeye.github_client using respx to mock httpx calls."""

import base64
import pytest
import respx
import httpx

from eagleeye.github_client import GitHubClient, GitHubAPIError


@pytest.fixture
def client():
    return GitHubClient("ghp_test_token")


@respx.mock
def test_get_pr_diff(client):
    diff_text = "--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,4 @@\n+import os\n"
    respx.get("https://api.github.com/repos/owner/repo/pulls/42").mock(
        return_value=httpx.Response(200, text=diff_text)
    )

    diff = client.get_pr_diff("owner", "repo", 42)
    assert "--- a/main.py" in diff


@respx.mock
def test_get_pr_metadata(client):
    payload = {
        "title": "Fix bug",
        "user": {"login": "alice"},
        "base": {"ref": "main"},
        "body": "Fixes #123",
        "html_url": "https://github.com/owner/repo/pull/42",
        "number": 42,
    }
    respx.get("https://api.github.com/repos/owner/repo/pulls/42").mock(
        return_value=httpx.Response(200, json=payload)
    )

    meta = client.get_pr_metadata("owner", "repo", 42)
    assert meta["title"] == "Fix bug"
    assert meta["author"] == "alice"
    assert meta["base"] == "main"


@respx.mock
def test_get_pr_files(client):
    files = [
        {"filename": "src/app.py", "additions": 10, "deletions": 2, "patch": "+foo"},
    ]
    respx.get("https://api.github.com/repos/owner/repo/pulls/42/files").mock(
        return_value=httpx.Response(200, json=files)
    )

    result = client.get_pr_files("owner", "repo", 42)
    assert result[0]["filename"] == "src/app.py"


@respx.mock
def test_get_repo_readme(client):
    readme_text = "# My Project\nThis is great."
    respx.get("https://api.github.com/repos/owner/repo/readme").mock(
        return_value=httpx.Response(200, text=readme_text)
    )

    readme = client.get_repo_readme("owner", "repo")
    assert "My Project" in readme


@respx.mock
def test_get_repo_readme_not_found_returns_empty(client):
    respx.get("https://api.github.com/repos/owner/repo/readme").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    readme = client.get_repo_readme("owner", "repo")
    assert readme == ""


@respx.mock
def test_get_file_content(client):
    content_b64 = base64.b64encode(b"print('hello')").decode()
    payload = {
        "encoding": "base64",
        "content": content_b64 + "\n",  # GitHub adds a newline
    }
    respx.get("https://api.github.com/repos/owner/repo/contents/main.py").mock(
        return_value=httpx.Response(200, json=payload)
    )

    content = client.get_file_content("owner", "repo", "main.py")
    assert "print('hello')" in content


@respx.mock
def test_api_error_raises(client):
    respx.get("https://api.github.com/repos/owner/repo/pulls/1").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    with pytest.raises(GitHubAPIError) as exc_info:
        client.get_pr_diff("owner", "repo", 1)

    assert exc_info.value.status_code == 404


@respx.mock
def test_post_pr_comment(client):
    respx.post("https://api.github.com/repos/owner/repo/issues/42/comments").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )

    # Should not raise
    client.post_pr_comment("owner", "repo", 42, "Great PR!")


@respx.mock
def test_list_open_prs(client):
    prs = [
        {
            "number": 1,
            "title": "Add feature",
            "user": {"login": "bob"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "html_url": "https://github.com/owner/repo/pull/1",
            "draft": False,
        }
    ]
    respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
        return_value=httpx.Response(200, json=prs)
    )

    result = client.list_open_prs("owner", "repo")
    assert result[0]["number"] == 1
    assert result[0]["author"] == "bob"


@respx.mock
def test_list_merged_prs(client):
    respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
        return_value=httpx.Response(200, json=[
            {"number": 5, "title": "Fix bug", "merged_at": "2026-04-01T10:00:00Z",
             "user": {"login": "alice"}, "body": "Fixes the thing"},
            {"number": 4, "title": "Draft PR", "merged_at": None,
             "user": {"login": "bob"}, "body": "WIP"},
        ])
    )
    result = client.list_merged_prs("owner", "repo", count=10)
    assert len(result) == 1
    assert result[0]["number"] == 5
    assert result[0]["author"] == "alice"
    assert result[0]["body_snippet"] == "Fixes the thing"
    assert result[0]["merged_at"] == "2026-04-01T10:00:00Z"


@respx.mock
def test_get_feature_store_files(client):
    respx.get("https://api.github.com/repos/owner/repo/git/trees/HEAD").mock(
        return_value=httpx.Response(200, json={"tree": [
            {"path": "src/feature_group.py", "type": "blob"},
            {"path": "src/load_features.py", "type": "blob"},
            {"path": "README.md", "type": "blob"},
            {"path": "src/", "type": "tree"},
        ]})
    )
    respx.get("https://api.github.com/repos/owner/repo/contents/src/feature_group.py").mock(
        return_value=httpx.Response(200, json={"content": "Y29sdW1uID0gZmxvYXQ=", "encoding": "base64"})
    )
    respx.get("https://api.github.com/repos/owner/repo/contents/src/load_features.py").mock(
        return_value=httpx.Response(200, json={"content": "bG9hZCA9IFRydWU=", "encoding": "base64"})
    )
    result = client.get_feature_store_files("owner", "repo")
    assert "src/feature_group.py" in result
    assert "src/load_features.py" in result
    assert "README.md" not in result


@respx.mock
def test_get_pr_files_paginates(client):
    page1 = [{"filename": f"file{i}.py", "status": "modified"} for i in range(100)]
    page2 = [{"filename": f"file{i}.py", "status": "modified"} for i in range(100, 130)]

    respx.get("https://api.github.com/repos/o/r/pulls/1/files").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
    )

    files = client.get_pr_files("o", "r", 1)
    assert len(files) == 130
