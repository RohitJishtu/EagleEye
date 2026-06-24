"""Context sub-app — manage saved repo contexts for cross-repo impact analysis."""

from __future__ import annotations

import json
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

context_app = typer.Typer(
    name="context",
    help="Manage saved repo contexts for cross-repo impact analysis.",
    no_args_is_help=True,
)


@context_app.command(name="save")
def context_save(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
    branch: Annotated[Optional[str], typer.Option("--branch", "-b")] = None,
    standard: Annotated[bool, typer.Option("--standard", help="Mark as always-include in every review")] = False,
    type_: Annotated[Optional[str], typer.Option("--type", help="Repo type hint: feature-store")] = None,
):
    """Analyze a repo and save its summary as reusable context."""
    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    from ..storage.context import save_context as store_context
    from ..storage.context import set_standard
    from ..features.repo_reader import run_repo_reader

    display_info(f"Analyzing {owner}/{repo_name} for context…")
    try:
        summary, _, _, file_tree = run_repo_reader(owner, repo_name, branch, config)
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)

    ctx_path = store_context(owner, repo_name, summary, file_tree)
    if standard:
        set_standard(owner, repo_name, True)
        display_success(f"Context saved and marked as standard: {ctx_path}")
    else:
        display_success(f"Context saved: {ctx_path}")
    display_info("Use --standard to auto-inject into every future review.")

    if type_ == "feature-store":
        from ..storage.catalog import build_catalog, save_catalog
        from ..integrations.github import GitHubClient
        display_info(f"Building feature catalog for {repo}…")
        github = GitHubClient(config.github_token)
        try:
            catalog_obj = build_catalog(owner, repo_name, github)
            save_catalog(catalog_obj)
            display_success(f"Feature catalog built: {len(catalog_obj.features)} feature(s).")
        except Exception as e:
            display_warning(f"Catalog build failed: {e}")
        finally:
            github.close()


@context_app.command(name="list")
def context_list():
    """List all saved repo contexts."""
    import datetime

    from rich import box
    from rich.table import Table

    from ..storage.context import list_contexts

    contexts = list_contexts()
    if not contexts:
        console.print("[dim]No saved contexts. Run: eagleeye context save owner/repo[/dim]")
        return

    table = Table(title="Saved Repo Contexts", box=box.ROUNDED)
    table.add_column("Repo", style="bold cyan")
    table.add_column("Standard", width=10)
    table.add_column("Stack", max_width=40)
    table.add_column("Saved", width=12, style="dim")

    for ctx in contexts:
        saved = datetime.datetime.fromtimestamp(ctx.saved_at).strftime("%Y-%m-%d")
        std = "[green]✓ yes[/green]" if ctx.is_standard else "[dim]no[/dim]"
        stack = ", ".join(ctx.tech_stack[:4])
        table.add_row(f"{ctx.owner}/{ctx.repo}", std, stack, saved)

    console.print(table)
    console.print(f"\n[dim]{len(contexts)} context(s). Standard repos are injected into every review.[/dim]")


@context_app.command(name="show")
def context_show(
    repo: Annotated[str, typer.Argument(help="owner/repo")],
):
    """Print the saved context for a repo."""
    from ..storage.context import load_context
    owner, repo_name = _parse_repo(repo)
    ctx = load_context(owner, repo_name)
    if not ctx:
        display_error(f"No saved context for {repo}. Run: eagleeye context save {repo}")
        raise typer.Exit(1)
    console.print_json(json.dumps(ctx.__dict__, indent=2, default=str))


@context_app.command(name="remove")
def context_remove(
    repo: Annotated[str, typer.Argument(help="owner/repo")],
):
    """Remove a saved context."""
    from ..storage.context import remove_context
    owner, repo_name = _parse_repo(repo)
    if remove_context(owner, repo_name):
        display_success(f"Context removed: {owner}/{repo_name}")
    else:
        display_warning(f"No context found for {owner}/{repo_name}")


@context_app.command(name="standard")
def context_standard(
    repo: Annotated[str, typer.Argument(help="owner/repo")],
):
    """Mark a saved context as always-include (injected into every review)."""
    from ..storage.context import set_standard
    owner, repo_name = _parse_repo(repo)
    if set_standard(owner, repo_name, True):
        display_success(f"{owner}/{repo_name} marked as standard — will be injected into every review.")
    else:
        display_error(f"No saved context for {repo}. Run: eagleeye context save {repo} first.")
        raise typer.Exit(1)


@context_app.command(name="unstandard")
def context_unstandard(
    repo: Annotated[str, typer.Argument(help="owner/repo")],
):
    """Remove always-include flag from a context."""
    from ..storage.context import set_standard
    owner, repo_name = _parse_repo(repo)
    if set_standard(owner, repo_name, False):
        display_success(f"{owner}/{repo_name} removed from standard contexts.")
    else:
        display_error(f"No saved context for {repo}.")
        raise typer.Exit(1)


@context_app.command(name="refresh")
def context_refresh(
    repo: Annotated[str, typer.Argument(help="owner/repo to refresh")],
):
    """Re-fetch a repo's architecture from GitHub and update the saved context."""
    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    from ..storage.context import load_context, set_standard
    from ..storage.context import save_context as store_context
    from ..features.repo_reader import run_repo_reader

    existing = load_context(owner, repo_name)
    display_info(f"Re-fetching {repo}…")
    try:
        summary, _, _, file_tree = run_repo_reader(owner, repo_name, None, config)
        store_context(owner, repo_name, summary, file_tree)
        if existing and existing.is_standard:
            set_standard(owner, repo_name, True)
        display_success(f"Context refreshed: {owner}/{repo_name}")
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)


@context_app.command(name="refresh-all")
def context_refresh_all():
    """Re-fetch architecture for all saved repo contexts."""
    config = _load_or_exit()
    from ..storage.context import list_contexts, set_standard
    from ..storage.context import save_context as store_context
    from ..features.repo_reader import run_repo_reader

    contexts = list_contexts()
    if not contexts:
        display_warning("No saved contexts.")
        return

    for ctx in contexts:
        display_info(f"Refreshing {ctx.owner}/{ctx.repo}…")
        try:
            summary, _, _, file_tree = run_repo_reader(ctx.owner, ctx.repo, None, config)
            store_context(ctx.owner, ctx.repo, summary, file_tree)
            if ctx.is_standard:
                set_standard(ctx.owner, ctx.repo, True)
            display_success(f"  ✓ {ctx.owner}/{ctx.repo}")
        except Exception as e:
            display_warning(f"  ✗ {ctx.owner}/{ctx.repo}: {e}")
