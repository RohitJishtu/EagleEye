"""Shared PR-fetch nodes used by the multi-agent review graph."""

from __future__ import annotations

from collections import deque
from typing import Any, Optional, TypedDict

from ..integrations.anthropic.client import TokenUsage
from ..integrations.github.pr_fetch import (
    SQL_MAX_FILE_BYTES,
    _extract_changed_symbols,
    cap_for,
    fetch_base_files_and_diff_symbols,
    fetch_cross_repo_callers,
    fetch_file_contents,
    fetch_pr_data,
    smart_truncate,
)
from ..core.models import PRReviewResult
from ..workflows.review.finalize import post_github_comment, save_review_file

__all__ = [
    "SQL_MAX_FILE_BYTES",
    "PRReviewState",
    "_extract_changed_symbols",
    "cap_for",
    "fetch_base_files_and_diff_symbols",
    "fetch_cross_repo_callers",
    "fetch_file_contents",
    "fetch_pr_data",
    "post_github_comment",
    "run_pr_review_graph",
    "save_review_file",
    "smart_truncate",
]


class PRReviewState(TypedDict):
    # Inputs
    owner: str
    repo: str
    pr_number: int
    post_comment: bool
    api_key: str
    github_token: str
    github_tokens: dict
    model: str
    max_tokens: int
    auth_mode: str
    proxy_client_id: str
    proxy_client_secret: str
    proxy_url: str
    token_url: str
    scope: str
    max_files: int
    max_file_bytes: int
    max_total_bytes: int
    # Fetched
    diff: str
    pr_metadata: dict
    file_list: list[str]
    full_file_contents: dict[str, str]
    base_file_contents: dict[str, str]
    structural_diff: Optional[Any]  # StructuralSymbolDiff at runtime
    # File fetch stats
    files_fetched: int
    files_total: int
    file_manifest: list
    # Internal state (rate limiting)
    search_window: deque[float]
    # Output
    result: Optional[PRReviewResult]
    schema_impact: Optional[Any]  # SchemaImpactResult — kept as Any to avoid TypedDict serialisation issues
    context_repos: Optional[list[str]]  # extra "owner/repo" slugs to inject as context
    token_usage: TokenUsage
    error: Optional[str]


def run_pr_review_graph(
    owner: str,
    repo: str,
    pr_number: int,
    post_comment: bool,
    config,
    context_repos: Optional[list[str]] = None,
) -> tuple[PRReviewResult, str, TokenUsage, Any, dict]:
    from .multi_agent import run_multi_agent_pr_review_graph
    return run_multi_agent_pr_review_graph(
        owner, repo, pr_number, post_comment, config, context_repos=context_repos
    )
