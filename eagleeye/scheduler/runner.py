"""APScheduler-based automated PR review scheduler.

Watches configured repositories on a cron schedule, finds unreviewed open PRs,
and runs the multi-agent review pipeline on each one.

Job state persists in ~/.eagleeye/scheduler.db (SQLite via APScheduler jobstore).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ..core.paths import reviews_dir

logger = logging.getLogger(__name__)

_SCHEDULER_DB = Path.home() / ".eagleeye" / "scheduler.db"

_scheduler: Optional[object] = None  # BackgroundScheduler, typed loosely to avoid import at module level


def _get_scheduler():
    """Lazily initialise and start the APScheduler BackgroundScheduler."""
    global _scheduler
    if _scheduler is None:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.schedulers.background import BackgroundScheduler

        _SCHEDULER_DB.parent.mkdir(parents=True, exist_ok=True)
        jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{_SCHEDULER_DB}")}
        _scheduler = BackgroundScheduler(jobstores=jobstores)

    if not _scheduler.running:  # type: ignore[union-attr]
        _scheduler.start()  # type: ignore[union-attr]

    return _scheduler


def add_scheduled_repo(
    owner: str,
    repo: str,
    cron_expression: str = "0 * * * *",
    post_comment: bool = True,
) -> str:
    """Register a cron job to review new PRs in owner/repo.

    Args:
        owner: GitHub organisation or user name.
        repo: Repository name.
        cron_expression: Standard 5-field cron string (default: hourly).
        post_comment: Whether to post the review as a GitHub PR comment.

    Returns:
        The APScheduler job ID.
    """
    scheduler = _get_scheduler()
    job_id = f"eagleeye-{owner}-{repo}"

    parts = cron_expression.split()
    if len(parts) == 5:
        trigger_kwargs = dict(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    else:
        trigger_kwargs = {"minute": "0"}  # fallback: top of every hour

    scheduler.add_job(  # type: ignore[union-attr]
        _scan_repo_for_new_prs,
        trigger="cron",
        id=job_id,
        replace_existing=True,
        kwargs={"owner": owner, "repo": repo, "post_comment": post_comment},
        **trigger_kwargs,
    )
    logger.info("Scheduled review job '%s' with cron '%s'", job_id, cron_expression)
    return job_id


def remove_scheduled_repo(owner: str, repo: str) -> bool:
    """Remove a scheduled review job.

    Returns True if the job was found and removed, False otherwise.
    """
    scheduler = _get_scheduler()
    job_id = f"eagleeye-{owner}-{repo}"
    try:
        scheduler.remove_job(job_id)  # type: ignore[union-attr]
        logger.info("Removed scheduled job '%s'", job_id)
        return True
    except Exception:
        return False


def list_scheduled_repos() -> list[dict]:
    """Return metadata for all scheduled review jobs."""
    scheduler = _get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():  # type: ignore[union-attr]
        jobs.append(
            {
                "job_id": job.id,
                "next_run": str(job.next_run_time),
                "trigger": str(job.trigger),
            }
        )
    return jobs


def _scan_repo_for_new_prs(owner: str, repo: str, post_comment: bool) -> None:
    """Cron job body: find unreviewed open PRs and review each one."""
    from ..core.config import load_config
    from ..features.pr_review import run_pr_review
    from ..integrations.github import GitHubClient

    try:
        config = load_config()
        github = GitHubClient(config.github_token)
        prs = github.list_open_prs(owner, repo)
        github.close()
    except Exception as exc:
        logger.error("Scheduler: failed to list PRs for %s/%s: %s", owner, repo, exc)
        return

    # Find PRs already reviewed by checking saved review files
    repo_reviews_dir = reviews_dir(owner, repo)
    reviewed_prs: set[int] = set()
    if repo_reviews_dir.exists():
        for f in repo_reviews_dir.glob("pr-*.md"):
            try:
                reviewed_prs.add(int(f.stem.split("-")[1]))
            except (IndexError, ValueError):
                pass

    for pr in prs:
        pr_number = pr["number"]
        if pr_number in reviewed_prs:
            continue
        logger.info("Scheduler: reviewing new PR #%d in %s/%s", pr_number, owner, repo)
        try:
            run_pr_review(owner, repo, pr_number, post_comment, config)
        except Exception as exc:
            logger.error(
                "Scheduler: review failed for %s/%s#%d: %s", owner, repo, pr_number, exc
            )


def shutdown() -> None:
    """Gracefully stop the scheduler (call on process exit)."""
    global _scheduler
    if _scheduler and getattr(_scheduler, "running", False):
        _scheduler.shutdown(wait=False)  # type: ignore[union-attr]
        _scheduler = None
