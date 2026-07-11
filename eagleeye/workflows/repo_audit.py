"""Deterministic repo audit workflow — priority file selection and checkers."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Optional

from ..core.config import EagleEyeConfig, resolve_github_token
from ..features.repo_auditor import AuditResult, run_audit
from ..integrations.github import GitHubClient
from ..workflows.repo_read.helpers import _select_key_files

SCANNABLE_EXTENSIONS = {".py", ".yml", ".yaml", ".sql", ".json", ".toml", ".ini", ".cfg"}
SCANNABLE_BASENAMES = {"dockerfile", "makefile"}
SKIP_PATH_PREFIXES = ("node_modules/", "vendor/", ".git/", "__pycache__/", ".mypy_cache/")
MAX_AUDIT_FILES = 60
MAX_FILE_BYTES = 20_000

_SECURITY_HOT_GLOBS = [
    "config*.yml", "config*.yaml", "config*.json",
    "*.env", "*.env.*", "secrets*", ".github/workflows/*",
    "Dockerfile", "docker-compose*.yml", "docker-compose*.yaml",
    "main.py", "app.py", "settings.py", "cicd/*",
]


@dataclass
class AuditCoverage:
    tree_files: int = 0
    audit_eligible: int = 0
    audit_scanned: int = 0
    excluded_paths: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "tree_files": self.tree_files,
            "audit_eligible": self.audit_eligible,
            "audit_scanned": self.audit_scanned,
            "excluded_paths": self.excluded_paths,
        }


def _should_skip_path(path: str) -> bool:
    lower = path.lower()
    return any(lower.startswith(p) or f"/{p}" in lower for p in SKIP_PATH_PREFIXES)


def is_scannable_path(path: str) -> bool:
    if _should_skip_path(path):
        return False
    basename = path.rsplit("/", 1)[-1].lower()
    if basename in SCANNABLE_BASENAMES:
        return True
    return any(path.lower().endswith(ext) for ext in SCANNABLE_EXTENSIONS)


def _is_security_hot(path: str) -> bool:
    filename = path.split("/")[-1]
    for pattern in _SECURITY_HOT_GLOBS:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(filename, pattern):
            return True
    return False


def select_priority_audit_paths(
    tree: list[dict],
    key_paths: Optional[list[str]] = None,
    path: Optional[str] = None,
    max_files: int = MAX_AUDIT_FILES,
) -> tuple[list[str], AuditCoverage]:
    """Select audit paths: key files + security-hot paths first, then fill remainder."""
    prefix = path.rstrip("/") + "/" if path else ""
    blobs = [
        item["path"]
        for item in tree
        if item.get("type") == "blob"
        and (not prefix or item["path"].startswith(prefix))
    ]

    eligible = [p for p in blobs if is_scannable_path(p)]
    coverage = AuditCoverage(
        tree_files=len(blobs),
        audit_eligible=len(eligible),
        excluded_paths=list(SKIP_PATH_PREFIXES),
    )

    selected: list[str] = []
    seen: set[str] = set()

    def add(paths: list[str]) -> None:
        for p in paths:
            if p in seen or not is_scannable_path(p):
                continue
            if prefix and not p.startswith(prefix):
                continue
            selected.append(p)
            seen.add(p)
            if len(selected) >= max_files:
                return

    add(key_paths or [])
    add([p for p in eligible if _is_security_hot(p)])
    add(eligible)

    coverage.audit_scanned = len(selected)
    return selected[:max_files], coverage


def fetch_file_contents(
    github: GitHubClient,
    owner: str,
    repo: str,
    branch: str,
    file_paths: list[str],
) -> dict[str, str]:
    contents: dict[str, str] = {}
    for file_path in file_paths:
        try:
            content = github.get_file_content(owner, repo, file_path, ref=branch)
            contents[file_path] = content[:MAX_FILE_BYTES]
        except Exception:
            pass
    return contents


def fetch_scannable_contents(
    github: GitHubClient,
    owner: str,
    repo: str,
    branch: str,
    path: Optional[str] = None,
    max_files: int = MAX_AUDIT_FILES,
    key_paths: Optional[list[str]] = None,
) -> tuple[dict[str, str], AuditCoverage]:
    """Fetch file contents for audit checkers with priority selection."""
    tree = github.get_repo_tree(owner, repo, branch)
    all_paths = [item["path"] for item in tree if item.get("type") == "blob"]
    if not key_paths:
        key_paths = _select_key_files(all_paths)
    file_paths, coverage = select_priority_audit_paths(
        tree, key_paths=key_paths, path=path, max_files=max_files,
    )
    contents = fetch_file_contents(github, owner, repo, branch, file_paths)
    return contents, coverage


def run_repo_audit(
    owner: str,
    repo: str,
    config: EagleEyeConfig,
    branch: Optional[str] = None,
    path: Optional[str] = None,
    key_paths: Optional[list[str]] = None,
) -> tuple[AuditResult, str, list[str], dict]:
    """Run deterministic health checks on a repository or subdirectory."""
    token = resolve_github_token(owner, config)
    github = GitHubClient(token)
    repo_slug = f"{owner}/{repo}"

    try:
        repo_meta = github.get_repo_metadata(owner, repo)
        effective_branch = branch or repo_meta.get("default_branch", "main")
        file_contents, coverage = fetch_scannable_contents(
            github, owner, repo, effective_branch, path=path, key_paths=key_paths,
        )
    finally:
        github.close()

    if not file_contents:
        result = AuditResult(repo=repo_slug, files_checked=0)
        return result, effective_branch, [], coverage.as_dict()

    result = run_audit(file_contents, repo=repo_slug)
    return result, effective_branch, list(file_contents.keys()), coverage.as_dict()
