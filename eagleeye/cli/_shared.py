"""Shared CLI helpers used across all command modules."""

from __future__ import annotations

import logging
import re
import sys

import typer

from ..core.config import (
    ConfigError,
    EagleEyeConfig,
    enable_langsmith_tracing,
    load_config,
)
from ..presentation.terminal import display_error


def _load_or_exit(require_claude: bool = True) -> EagleEyeConfig:
    enable_langsmith_tracing()
    try:
        return load_config(require_claude=require_claude)
    except ConfigError as e:
        display_error(str(e))
        raise typer.Exit(1)


def _parse_repo(repo_arg: str) -> tuple[str, str]:
    """Parse 'owner/repo' into (owner, repo). Exits on invalid format."""
    parts = repo_arg.strip().split("/")
    if len(parts) != 2 or not all(parts):
        display_error(f"Invalid repo format: '{repo_arg}'. Expected 'owner/repo'.")
        raise typer.Exit(1)
    return parts[0], parts[1]


def _parse_github_url(url: str) -> tuple[str, str, int] | None:
    """Parse a GitHub PR URL into (owner, repo, pr_number), or return None."""
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)",
        url.strip(),
    )
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    return None


def _enable_debug() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(name)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
