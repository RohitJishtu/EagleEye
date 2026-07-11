"""eagleeye understand — lightweight repo mapping (no full LLM read)."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from ..presentation.terminal import display_error, display_repo_map, display_success
from ..storage.maps import load_map, save_map
from ..workflows.understand_build import build_repo_map
from ._shared import _load_or_exit, _parse_repo

understand_app = typer.Typer(
    name="understand",
    help="Build lightweight repo maps for faster onboarding and review context.",
    no_args_is_help=True,
)


@understand_app.command(name="build")
def understand_build(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
    branch: Annotated[Optional[str], typer.Option("--branch", "-b", help="Branch to analyze")] = None,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output format: json")] = None,
):
    """Build a deterministic RepoMap (tree, README, signals) and save to ~/.eagleeye/maps/."""
    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    try:
        repo_map = build_repo_map(owner, repo_name, config, branch=branch)
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)

    saved_path = save_map(repo_map)

    if output == "json":
        typer.echo(repo_map.model_dump_json(indent=2))
    else:
        display_repo_map(repo_map, saved_path=saved_path)
        display_success(f"Repo map saved: {saved_path}")


@understand_app.command(name="show")
def understand_show(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output format: json")] = None,
):
    """Show a previously built RepoMap from ~/.eagleeye/maps/."""
    owner, repo_name = _parse_repo(repo)
    repo_map = load_map(owner, repo_name)
    if repo_map is None:
        display_error(
            f"No map for {owner}/{repo_name}. Run: eagleeye understand build {owner}/{repo_name}"
        )
        raise typer.Exit(1)

    if output == "json":
        typer.echo(repo_map.model_dump_json(indent=2))
    else:
        display_repo_map(repo_map)
