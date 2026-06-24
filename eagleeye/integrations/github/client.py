"""GitHub REST API v3 client for EagleEye."""

from __future__ import annotations

import base64
from typing import Any

import httpx


class GitHubAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"GitHub API error {status_code}: {message}")


_BASE = "https://api.github.com"
_HEADERS = {
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "EagleEye/0.1.0",
}


class GitHubClient:
    def __init__(self, token: str):
        self._client = httpx.Client(
            headers={**_HEADERS, "Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    def _get(self, path: str, accept: str = "application/vnd.github+json", **params) -> Any:
        resp = self._client.get(f"{_BASE}{path}", headers={"Accept": accept}, params=params)
        if not resp.is_success:
            try:
                msg = resp.json().get("message", resp.text)
            except Exception:
                msg = resp.text
            raise GitHubAPIError(resp.status_code, msg)
        return resp

    def _get_json(self, path: str, **params) -> Any:
        return self._get(path, **params).json()

    # ------------------------------------------------------------------
    # PR methods
    # ------------------------------------------------------------------

    def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Fetch the raw unified diff for a pull request."""
        resp = self._get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            accept="application/vnd.github.v3.diff",
        )
        return resp.text

    def get_pr_metadata(self, owner: str, repo: str, pr_number: int) -> dict:
        """Fetch PR title, author, base branch, description."""
        data = self._get_json(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        merged_at = data.get("merged_at") or ""
        gh_state = data.get("state", "open")  # "open" | "closed"
        pr_status = "merged" if merged_at else gh_state
        return {
            "title": data.get("title", ""),
            "author": data.get("user", {}).get("login", "unknown"),
            "base": data.get("base", {}).get("ref", "main"),
            "body": data.get("body") or "",
            "html_url": data.get("html_url", ""),
            "number": data.get("number"),
            "merged_at": merged_at,
            "head_sha": data.get("head", {}).get("sha", ""),
            "pr_status": pr_status,
        }

    def get_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        """Fetch the list of files changed in a PR (paginates through all pages)."""
        all_files: list[dict] = []
        page = 1
        while True:
            batch = self._get_json(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
                per_page=100,
                page=page,
            )
            all_files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return all_files

    def post_pr_comment(self, owner: str, repo: str, pr_number: int, body: str) -> None:
        """Post a comment on a PR (via the issues comment endpoint)."""
        resp = self._client.post(
            f"{_BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments",
            headers={"Accept": "application/vnd.github+json"},
            json={"body": body},
        )
        if not resp.is_success:
            try:
                msg = resp.json().get("message", resp.text)
            except Exception:
                msg = resp.text
            raise GitHubAPIError(resp.status_code, msg)

    def submit_pr_review(self, owner: str, repo: str, pr_number: int, event: str, body: str) -> None:
        """Submit a formal PR review. event: APPROVE | REQUEST_CHANGES | COMMENT."""
        resp = self._client.post(
            f"{_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers={"Accept": "application/vnd.github+json"},
            json={"body": body, "event": event},
        )
        if not resp.is_success:
            try:
                msg = resp.json().get("message", resp.text)
            except Exception:
                msg = resp.text
            raise GitHubAPIError(resp.status_code, msg)

    def list_open_prs(self, owner: str, repo: str) -> list[dict]:
        """List open PRs for a repo."""
        prs = self._get_json(f"/repos/{owner}/{repo}/pulls", state="open", per_page=100)
        return [
            {
                "number": pr["number"],
                "title": pr["title"],
                "author": pr.get("user", {}).get("login", ""),
                "created_at": pr.get("created_at", ""),
                "updated_at": pr.get("updated_at", ""),
                "html_url": pr.get("html_url", ""),
                "draft": pr.get("draft", False),
            }
            for pr in prs
        ]

    def list_merged_prs(self, owner: str, repo: str, count: int = 20) -> list[dict]:
        """List recently merged PRs for a repo."""
        prs = self._get_json(
            f"/repos/{owner}/{repo}/pulls",
            state="closed",
            per_page=min(count, 100),
        )
        result = []
        for pr in prs:
            if pr.get("merged_at") is None:
                continue
            body = pr.get("body") or ""
            result.append(
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "merged_at": pr["merged_at"],
                    "author": pr.get("user", {}).get("login", ""),
                    "body_snippet": body[:300],
                }
            )
        return result

    def get_feature_store_files(self, owner: str, repo: str, max_files: int = 60) -> dict[str, str]:
        """Fetch content of feature-store-related files in a repo."""
        try:
            from ...analysis.feature_store import _is_feature_file
        except ImportError:
            # Fallback: inline the classifier so tree_sitter issues don't block this method.
            def _is_feature_file(path: str) -> bool:  # type: ignore[misc]
                p = path.lower()
                keywords = (
                    "feature", "featuregroup", "feature_group", "feature_store",
                    "train", "training", "infer", "score", "register_model",
                    "model_register", "feature_load", "load_feature",
                )
                return any(kw in p for kw in keywords)
        data = self._get_json(
            f"/repos/{owner}/{repo}/git/trees/HEAD",
            recursive="1",
        )
        tree = data.get("tree", [])
        feature_items = [
            item for item in tree
            if item.get("type") == "blob" and _is_feature_file(item["path"])
        ]
        contents: dict[str, str] = {}
        for item in feature_items[:max_files]:
            try:
                contents[item["path"]] = self.get_file_content(owner, repo, item["path"])
            except GitHubAPIError:
                pass
        return contents

    # ------------------------------------------------------------------
    # Repo methods
    # ------------------------------------------------------------------

    def get_repo_metadata(self, owner: str, repo: str) -> dict:
        """Fetch top-level repo info."""
        data = self._get_json(f"/repos/{owner}/{repo}")
        return {
            "name": data.get("name", repo),
            "full_name": data.get("full_name", f"{owner}/{repo}"),
            "description": data.get("description") or "",
            "language": data.get("language") or "",
            "topics": data.get("topics", []),
            "default_branch": data.get("default_branch", "main"),
            "stargazers_count": data.get("stargazers_count", 0),
            "html_url": data.get("html_url", ""),
        }

    def get_repo_readme(self, owner: str, repo: str) -> str:
        """Fetch the README as plain text."""
        try:
            resp = self._get(
                f"/repos/{owner}/{repo}/readme",
                accept="application/vnd.github.v3.raw",
            )
            return resp.text
        except GitHubAPIError as e:
            if e.status_code == 404:
                return ""
            raise

    def get_repo_tree(self, owner: str, repo: str, branch: str = "HEAD") -> list[dict]:
        """Fetch the full file tree recursively."""
        # First resolve the branch SHA
        try:
            ref_data = self._get_json(f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
            sha = ref_data["object"]["sha"]
        except GitHubAPIError:
            # Fall back to repo default branch info
            repo_meta = self._get_json(f"/repos/{owner}/{repo}")
            default = repo_meta.get("default_branch", "main")
            ref_data = self._get_json(f"/repos/{owner}/{repo}/git/ref/heads/{default}")
            sha = ref_data["object"]["sha"]

        data = self._get_json(
            f"/repos/{owner}/{repo}/git/trees/{sha}",
            recursive="1",
        )
        return data.get("tree", [])

    def get_file_content(self, owner: str, repo: str, path: str, ref: str = "HEAD") -> str:
        """Fetch the decoded text content of a file."""
        data = self._get_json(f"/repos/{owner}/{repo}/contents/{path}", ref=ref)
        if isinstance(data, list):
            raise GitHubAPIError(0, f"{path} is a directory, not a file")
        encoding = data.get("encoding", "base64")
        if encoding == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return data.get("content", "")

    def list_org_repos(self, owner: str, type: str = "all", per_page: int = 100) -> list[dict]:
        """List repos for an org or user."""
        try:
            # Try org endpoint first
            repos = self._get_json(
                f"/orgs/{owner}/repos",
                type=type,
                per_page=per_page,
                sort="updated",
            )
        except GitHubAPIError:
            # Fall back to user repos
            repos = self._get_json(
                f"/users/{owner}/repos",
                type=type,
                per_page=per_page,
                sort="updated",
            )
        return [
            {
                "name": r["name"],
                "full_name": r["full_name"],
                "description": r.get("description") or "",
                "language": r.get("language") or "",
                "topics": r.get("topics", []),
                "default_branch": r.get("default_branch", "main"),
                "updated_at": r.get("updated_at", ""),
                "html_url": r.get("html_url", ""),
                "archived": r.get("archived", False),
                "fork": r.get("fork", False),
            }
            for r in repos
        ]

    def search_code(self, owner: str, repo: str, symbol: str, per_page: int = 10) -> list[str]:
        """Search the repo for files containing a symbol name. Returns file paths."""
        try:
            data = self._get_json(
                "/search/code",
                q=f"{symbol} repo:{owner}/{repo}",
                per_page=per_page,
            )
            return [item["path"] for item in data.get("items", [])]
        except GitHubAPIError:
            return []

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
