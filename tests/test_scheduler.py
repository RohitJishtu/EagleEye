"""Tests for the EagleEye scheduler (APScheduler-based)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch



# ---------------------------------------------------------------------------
# add_scheduled_repo
# ---------------------------------------------------------------------------


def test_add_scheduled_repo_registers_job():
    """add_scheduled_repo must call scheduler.add_job with the right ID."""
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with (
        patch("eagleeye.scheduler.runner._get_scheduler", return_value=mock_scheduler),
    ):
        from eagleeye.scheduler.runner import add_scheduled_repo

        job_id = add_scheduled_repo("owner", "repo", cron_expression="0 * * * *")

    assert job_id == "eagleeye-owner-repo"
    mock_scheduler.add_job.assert_called_once()
    call_kwargs = mock_scheduler.add_job.call_args
    assert call_kwargs.kwargs["id"] == "eagleeye-owner-repo"
    assert call_kwargs.kwargs["replace_existing"] is True


def test_add_scheduled_repo_default_cron_is_hourly():
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with patch("eagleeye.scheduler.runner._get_scheduler", return_value=mock_scheduler):
        from eagleeye.scheduler.runner import add_scheduled_repo

        add_scheduled_repo("a", "b")

    call_kwargs = mock_scheduler.add_job.call_args.kwargs
    # Default hourly: minute=0, hour=*
    assert call_kwargs.get("minute") == "0"


# ---------------------------------------------------------------------------
# remove_scheduled_repo
# ---------------------------------------------------------------------------


def test_remove_scheduled_repo_existing():
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with patch("eagleeye.scheduler.runner._get_scheduler", return_value=mock_scheduler):
        from eagleeye.scheduler.runner import remove_scheduled_repo

        result = remove_scheduled_repo("owner", "repo")

    assert result is True
    mock_scheduler.remove_job.assert_called_once_with("eagleeye-owner-repo")


def test_remove_scheduled_repo_not_found():
    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    mock_scheduler.remove_job.side_effect = Exception("job not found")

    with patch("eagleeye.scheduler.runner._get_scheduler", return_value=mock_scheduler):
        from eagleeye.scheduler.runner import remove_scheduled_repo

        result = remove_scheduled_repo("owner", "nonexistent")

    assert result is False


# ---------------------------------------------------------------------------
# list_scheduled_repos
# ---------------------------------------------------------------------------


def test_list_scheduled_repos_empty():
    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    mock_scheduler.get_jobs.return_value = []

    with patch("eagleeye.scheduler.runner._get_scheduler", return_value=mock_scheduler):
        from eagleeye.scheduler.runner import list_scheduled_repos

        jobs = list_scheduled_repos()

    assert jobs == []


def test_list_scheduled_repos_returns_metadata():
    mock_job = MagicMock()
    mock_job.id = "eagleeye-owner-repo"
    mock_job.next_run_time = "2026-04-24 09:00:00"
    mock_job.trigger = "cron[hour='*', minute='0']"

    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    mock_scheduler.get_jobs.return_value = [mock_job]

    with patch("eagleeye.scheduler.runner._get_scheduler", return_value=mock_scheduler):
        from eagleeye.scheduler.runner import list_scheduled_repos

        jobs = list_scheduled_repos()

    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "eagleeye-owner-repo"


# ---------------------------------------------------------------------------
# _scan_repo_for_new_prs
# ---------------------------------------------------------------------------


def test_scan_repo_skips_already_reviewed(tmp_path, monkeypatch):
    """PRs that already have a saved review file must not be re-reviewed."""
    reviews_root = tmp_path / "reviews"
    reviews_dir = reviews_root / "owner-repo"
    reviews_dir.mkdir(parents=True)
    (reviews_dir / "pr-5-some-title.md").write_text("reviewed")
    monkeypatch.setenv("EAGLEEYE_REVIEWS_DIR", str(reviews_root))

    mock_config = MagicMock()
    mock_config.github_token = "ghp_test"

    mock_github = MagicMock()
    mock_github.list_open_prs.return_value = [
        {"number": 5, "title": "Already reviewed"},
        {"number": 6, "title": "New PR"},
    ]
    mock_github.close = MagicMock()

    reviewed_pr_numbers: list[int] = []

    def fake_run_pr_review(owner, repo, pr_number, post_comment, config):
        reviewed_pr_numbers.append(pr_number)

    # Lazy imports inside _scan_repo_for_new_prs are patched at their source module
    with (
        patch("eagleeye.core.config.load_config", return_value=mock_config),
        patch("eagleeye.integrations.github.GitHubClient", return_value=mock_github),
        patch("eagleeye.features.pr_review.run_pr_review", side_effect=fake_run_pr_review),
    ):
        from eagleeye.scheduler.runner import _scan_repo_for_new_prs

        _scan_repo_for_new_prs("owner", "repo", post_comment=False)

    assert 5 not in reviewed_pr_numbers
    assert 6 in reviewed_pr_numbers


def test_scan_repo_handles_github_error():
    """A GitHub API failure must not raise — it must be logged and swallowed."""
    mock_config = MagicMock()

    mock_github = MagicMock()
    mock_github.list_open_prs.side_effect = Exception("API error")
    mock_github.close = MagicMock()

    with (
        patch("eagleeye.core.config.load_config", return_value=mock_config),
        patch("eagleeye.integrations.github.GitHubClient", return_value=mock_github),
        patch("eagleeye.features.pr_review.run_pr_review") as mock_review,
    ):
        from eagleeye.scheduler.runner import _scan_repo_for_new_prs

        # Must not raise
        _scan_repo_for_new_prs("owner", "repo", post_comment=False)

    mock_review.assert_not_called()
