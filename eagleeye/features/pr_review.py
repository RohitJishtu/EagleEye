"""PR Review feature: fetch a GitHub PR and get an AI-powered review."""

from __future__ import annotations

from typing import Any, Optional

from ..integrations.anthropic.client import TokenUsage
from ..core.config import EagleEyeConfig
from ..core.models import PRReviewResult
from ..workflows.review import (
    enforce_verdict_rules,
    format_comment_markdown,
    group_similar_findings,
    save_review,
    slugify_title,
)
from ..workflows.review.formatting import edp_downstream

# Backward-compatible aliases for private names used by tests and callers.
_format_comment_markdown = format_comment_markdown
_save_review = save_review
_group_similar_findings = group_similar_findings
_edp_downstream = edp_downstream

__all__ = [
    "_edp_downstream",
    "_format_comment_markdown",
    "_group_similar_findings",
    "_save_review",
    "enforce_verdict_rules",
    "run_pr_review",
    "slugify_title",
]


def run_pr_review(
    owner: str,
    repo: str,
    pr_number: int,
    post_comment: bool,
    config: EagleEyeConfig,
    context_repos: Optional[list[str]] = None,
) -> tuple[PRReviewResult, str, TokenUsage, Optional[Any], dict]:
    from ..graphs.pr_review import run_pr_review_graph

    return run_pr_review_graph(
        owner, repo, pr_number, post_comment, config, context_repos=context_repos
    )
