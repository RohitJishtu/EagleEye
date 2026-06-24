"""History sub-app — manage the per-repo PR history index."""

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
from ..cli._shared import _load_or_exit, _parse_repo

history_app = typer.Typer(
    name="history",
    help="Manage the per-repo PR history index.",
    no_args_is_help=True,
)


@history_app.command(name="seed")
def history_seed(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
    count: Annotated[int, typer.Option("--count", help="Number of merged PRs to fetch")] = 20,
):
    """Backfill the PR history index with past merged PRs from GitHub."""
    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    from ..integrations.github import GitHubClient
    from ..storage.history import PRHistoryEntry, add_entry

    display_info(f"Fetching last {count} merged PRs from {repo}…")
    github = GitHubClient(config.github_token)
    try:
        prs = github.list_merged_prs(owner, repo_name, count=count)
        for pr in prs:
            try:
                files = [
                    f["filename"]
                    for f in github.get_pr_files(owner, repo_name, pr["number"])
                ]
            except Exception:
                files = []
            add_entry(owner, repo_name, PRHistoryEntry(
                pr_number=pr["number"],
                title=pr["title"],
                merged_at=pr["merged_at"],
                author=pr["author"],
                files_changed=files,
                body_snippet=pr["body_snippet"],
            ))
        display_success(f"Seeded {len(prs)} PR(s) into history index for {repo}.")
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)
    finally:
        github.close()


@history_app.command(name="list")
def history_list(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
):
    """Show the PR history index for a repo."""
    from rich import box
    from rich.table import Table

    owner, repo_name = _parse_repo(repo)
    from ..storage.history import load_history

    history = load_history(owner, repo_name)
    if not history:
        console.print(f"[dim]No history for {repo}. Run: eagleeye history seed {repo}[/dim]")
        return

    table = Table(title=f"PR History — {repo}", box=box.ROUNDED)
    table.add_column("#", width=6, style="bold cyan")
    table.add_column("Title", max_width=50)
    table.add_column("Risk", width=10)
    table.add_column("Verdict", width=18)
    table.add_column("Date", width=12, style="dim")
    table.add_column("Files", width=6)

    for e in sorted(history, key=lambda x: x.merged_at or "", reverse=True):
        risk_color = {
            "critical": "red", "high": "orange3", "medium": "yellow", "low": "green"
        }.get(e.risk_level or "", "white")
        table.add_row(
            str(e.pr_number),
            e.title,
            f"[{risk_color}]{(e.risk_level or '—').upper()}[/{risk_color}]",
            e.verdict or "—",
            (e.merged_at or "")[:10],
            str(len(e.files_changed)),
        )

    console.print(table)
