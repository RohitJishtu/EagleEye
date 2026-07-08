"""Tests for eagleeye.features.pr_review — GitHubClient and AIClient are mocked."""

import pytest
from unittest.mock import patch

from eagleeye.config import EagleEyeConfig
from eagleeye.features.pr_review import run_pr_review, _format_comment_markdown
from eagleeye.models import FileComment, PRReviewResult


@pytest.fixture
def config():
    return EagleEyeConfig(
        github_token="ghp_test",
        anthropic_api_key="sk-ant-test",
        model="claude-sonnet-4-6",
    )


@pytest.fixture
def sample_review():
    return PRReviewResult(
        summary="Good PR with minor issues.",
        overall_verdict="approve",
        risk_level="low",
        file_comments=[
            FileComment(
                file="src/app.py",
                line_range="12",
                severity="low",
                category="style",
                comment="Variable name could be more descriptive.",
                suggestion="Rename `x` to `user_count`.",
            )
        ],
        positive_highlights=["Good test coverage"],
        blocking_issues=[],
        estimated_review_time_minutes=8,
    )


def test_run_pr_review_calls_graph(config, sample_review):
    from eagleeye.ai_client import TokenUsage

    with patch(
        "eagleeye.graphs.pr_review.run_pr_review_graph",
        return_value=(sample_review, "mock diff", TokenUsage(), None, {"title": "Test PR", "author": "dev"}),
    ) as mock_graph:
        result, diff, _, _, _ = run_pr_review("owner", "repo", 1, post_comment=False, config=config)

    assert result.overall_verdict == "approve"
    mock_graph.assert_called_once_with("owner", "repo", 1, False, config, context_repos=None)


def test_run_pr_review_passes_post_comment_flag(config, sample_review):
    from eagleeye.ai_client import TokenUsage

    with patch(
        "eagleeye.graphs.pr_review.run_pr_review_graph",
        return_value=(sample_review, "diff", TokenUsage(), None, {}),
    ) as mock_graph:
        run_pr_review("o", "r", 5, post_comment=True, config=config)

    _, _, _, post_comment_arg, _ = mock_graph.call_args[0]
    assert post_comment_arg is True


def test_format_comment_markdown_approve(sample_review):
    md = _format_comment_markdown(sample_review, "https://github.com/o/r/pull/1")
    assert "EagleEye" in md
    assert "Okay to merge" in md
    assert "Good test coverage" in md
    assert "```" not in md  # should be plain markdown, not code fence


def test_format_comment_markdown_blocking_issues():
    review = PRReviewResult(
        summary="Critical issues found.",
        overall_verdict="request_changes",
        risk_level="critical",
        blocking_issues=["SQL injection in db.py", "Auth bypass in auth.py"],
        positive_highlights=[],
        file_comments=[],
        estimated_review_time_minutes=15,
    )
    md = _format_comment_markdown(review)
    assert "Blocking Issues" in md
    assert "SQL injection" in md
    assert "Auth bypass" in md
