"""Repo Reader feature: analyze a GitHub repo's architecture and produce an onboarding doc."""

from __future__ import annotations

from typing import Optional

from ..integrations.anthropic.client import TokenUsage
from ..core.config import EagleEyeConfig
from ..core.models import RepoSummaryResult
from ..workflows.repo_read.helpers import (
    _build_tree_string,
    _select_key_files,
)

__all__ = [
    "_build_tree_string",
    "_select_key_files",
    "run_repo_reader",
]


def run_repo_reader(
    owner: str,
    repo: str,
    branch: Optional[str],
    config: EagleEyeConfig,
) -> tuple[RepoSummaryResult, str, TokenUsage, list[dict]]:
    """Analyze a repo and return (summary, repo_url, token_usage, file_tree)."""
    from ..graphs.repo_reader import run_repo_reader_graph

    return run_repo_reader_graph(owner, repo, branch, config)
