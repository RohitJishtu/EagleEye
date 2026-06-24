"""Repo-read workflow helpers: key file selection and tree formatting."""

from __future__ import annotations

import fnmatch

# Priority patterns for key file selection (checked in order)
_PRIORITY_PATTERNS = [
    "README.md",
    "README.rst",
    "readme.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "src/main.*",
    "src/app.*",
    "src/index.*",
    "main.py",
    "app.py",
    "index.js",
    "index.ts",
    "dbt_project.yml",
    "airflow_settings.yaml",
    "dagster.yaml",
    "prefect.yaml",
    "config/*.py",
    "config/*.yaml",
    "config/*.yml",
    "docs/ARCHITECTURE.md",
    "docs/architecture.md",
]

_MAX_KEY_FILES = 10
_MAX_FILE_BYTES = 5_000


def _select_key_files(all_paths: list[str]) -> list[str]:
    """Select up to _MAX_KEY_FILES paths from the repo tree based on priority patterns."""
    selected = []
    seen = set()

    for pattern in _PRIORITY_PATTERNS:
        if len(selected) >= _MAX_KEY_FILES:
            break
        for path in all_paths:
            if path in seen:
                continue
            filename = path.split("/")[-1]
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(filename, pattern):
                selected.append(path)
                seen.add(path)
                if len(selected) >= _MAX_KEY_FILES:
                    break

    return selected


def _build_tree_string(tree: list[dict], max_entries: int = 200) -> str:
    """Build a compact directory tree string from the GitHub tree API response."""
    dirs = set()
    files = []

    for item in tree[:max_entries]:
        path = item.get("path", "")
        if item.get("type") == "tree":
            dirs.add(path)
        else:
            files.append(path)

    lines = []
    for path in sorted(files):
        lines.append(f"  {path}")

    if len(tree) > max_entries:
        lines.append(f"  ... ({len(tree) - max_entries} more files)")

    return "\n".join(lines)
