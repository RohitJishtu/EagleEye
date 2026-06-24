"""Catalog sub-app — manage the feature store catalog."""

from __future__ import annotations

import time
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

catalog_app = typer.Typer(
    name="catalog",
    help="Manage the feature store catalog for cross-repo lineage.",
    no_args_is_help=True,
)


@catalog_app.command(name="build")
def catalog_build(
    repo: Annotated[str, typer.Argument(help="Feature store repo in owner/repo format")],
):
    """Build feature catalog by fetching and analysing a feature store repo."""
    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    from ..storage.catalog import build_catalog, save_catalog
    from ..integrations.github import GitHubClient

    display_info(f"Fetching feature files from {repo}…")
    github = GitHubClient(config.github_token)
    try:
        catalog = build_catalog(owner, repo_name, github)
        path = save_catalog(catalog)
        display_success(f"Catalog built: {len(catalog.features)} feature(s) → {path}")
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)
    finally:
        github.close()


@catalog_app.command(name="refresh")
def catalog_refresh(
    repo: Annotated[str, typer.Argument(help="Feature store repo in owner/repo format")],
):
    """Re-fetch the feature store repo and update the catalog (preserves consumers)."""
    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    from ..storage.catalog import refresh_catalog
    from ..integrations.github import GitHubClient

    display_info(f"Refreshing catalog for {repo}…")
    github = GitHubClient(config.github_token)
    try:
        catalog = refresh_catalog(owner, repo_name, github)
        display_success(f"Catalog refreshed: {len(catalog.features)} feature(s) tracked.")
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)
    finally:
        github.close()


@catalog_app.command(name="list")
def catalog_list(
    repo: Annotated[str, typer.Argument(help="Feature store repo in owner/repo format")],
):
    """List all features in the catalog with consumer counts."""
    import time

    from rich import box
    from rich.table import Table

    owner, repo_name = _parse_repo(repo)
    from ..storage.catalog import is_stale, load_catalog

    catalog = load_catalog(owner, repo_name)
    if not catalog:
        display_error(f"No catalog found for {repo}. Run: eagleeye catalog build {repo}")
        raise typer.Exit(1)

    age_days = int((time.time() - catalog.refreshed_at) / 86400)
    stale_note = " ⚠️  stale" if is_stale(catalog) else ""
    console.print(
        f"\n[bold]Feature Catalog — {repo}[/bold]  "
        f"[dim](refreshed {age_days}d ago{stale_note})[/dim]\n"
    )

    table = Table(box=box.ROUNDED, show_lines=False)
    table.add_column("Feature", style="bold cyan")
    table.add_column("Group", style="dim")
    table.add_column("Type", style="dim")
    table.add_column("Load Jobs", max_width=30)
    table.add_column("Consumers", width=10)

    for entry in sorted(catalog.features.values(), key=lambda e: e.feature_name):
        table.add_row(
            entry.feature_name,
            entry.feature_group,
            entry.feature_type or "—",
            ", ".join(entry.load_jobs) or "—",
            str(len(entry.consumers)),
        )

    console.print(table)
    console.print(f"\n[dim]{len(catalog.features)} feature(s) tracked.[/dim]")


@catalog_app.command(name="show")
def catalog_show(
    repo: Annotated[str, typer.Argument(help="Feature store repo in owner/repo format")],
    feature: Annotated[str, typer.Argument(help="Feature name to inspect")],
):
    """Show full lineage for a single feature."""
    owner, repo_name = _parse_repo(repo)
    from ..storage.catalog import load_catalog

    catalog = load_catalog(owner, repo_name)
    if not catalog:
        display_error(f"No catalog found for {repo}.")
        raise typer.Exit(1)

    entry = catalog.features.get(feature)
    if not entry:
        display_error(f"Feature '{feature}' not found in catalog.")
        raise typer.Exit(1)

    console.print(f"\n[bold cyan]{entry.feature_name}[/bold cyan]")
    console.print(f"  Group:     {entry.feature_group}")
    console.print(f"  Type:      {entry.feature_type or '—'}")
    console.print(f"  Defined:   {entry.source_file}")
    console.print(f"  Load jobs: {', '.join(entry.load_jobs) or '—'}")
    console.print(f"\n  [bold]Consumers ({len(entry.consumers)}):[/bold]")
    for c in entry.consumers:
        console.print(f"    [{c.role}]  {c.repo} / {c.file}:{c.line}")
        console.print(f"             {c.snippet}")
