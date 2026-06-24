"""Schedule sub-app — schedule automated PR reviews on a cron interval."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from ..presentation.terminal import (
    console,
    display_error,
    display_info,
    display_success,
    display_warning,
)
from ..cli._shared import _parse_repo

schedule_app = typer.Typer(
    name="schedule",
    help="Schedule automated PR reviews on a cron interval.",
    no_args_is_help=True,
)


def _require_apscheduler() -> None:
    try:
        import apscheduler  # noqa: F401
    except ImportError:
        display_error("apscheduler is required. Run: pip install 'eagleeye[scheduler]'")
        raise typer.Exit(1)


@schedule_app.command(name="add")
def schedule_add(
    repo: Annotated[str, typer.Argument(help="owner/repo to watch")],
    cron: Annotated[str, typer.Option("--cron", help="5-field cron expression")] = "0 * * * *",
    no_post: Annotated[bool, typer.Option("--no-post", help="Analyse only, do not post GitHub comment")] = False,
):
    """Add a repo to the review schedule.

    Unreviewed open PRs are reviewed on each cron firing.

    Examples:
      eagleeye schedule add owner/repo                    # hourly
      eagleeye schedule add owner/repo --cron "0 9 * * 1-5"  # weekdays at 09:00
    """
    _require_apscheduler()
    owner, repo_name = _parse_repo(repo)
    from ..scheduler.runner import add_scheduled_repo
    job_id = add_scheduled_repo(owner, repo_name, cron, post_comment=not no_post)
    display_success(f"Scheduled: {repo} — job ID: {job_id}  cron: {cron}")
    display_info("Run 'eagleeye schedule list' to see all scheduled repos.")


@schedule_app.command(name="list")
def schedule_list():
    """List all scheduled review jobs and their next run times."""
    _require_apscheduler()
    import rich.box as box
    from rich.table import Table

    from ..scheduler.runner import list_scheduled_repos

    jobs = list_scheduled_repos()
    if not jobs:
        console.print("[dim]No scheduled repos. Run: eagleeye schedule add owner/repo[/dim]")
        return

    table = Table(title="Scheduled Reviews", box=box.ROUNDED)
    table.add_column("Job ID", style="bold cyan")
    table.add_column("Next Run")
    table.add_column("Trigger")
    for job in jobs:
        table.add_row(job["job_id"], job["next_run"], job["trigger"])
    console.print(table)


@schedule_app.command(name="remove")
def schedule_remove(
    repo: Annotated[str, typer.Argument(help="owner/repo to unschedule")],
):
    """Remove a repo from the review schedule."""
    _require_apscheduler()
    owner, repo_name = _parse_repo(repo)
    from ..scheduler.runner import remove_scheduled_repo
    if remove_scheduled_repo(owner, repo_name):
        display_success(f"Removed from schedule: {repo}")
    else:
        display_warning(f"No scheduled job found for {repo}")
