"""Reference sub-app — manage reference repo indexes for cross-repo dependency checking."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from ..presentation.terminal import (
    display_error,
    display_info,
    display_success,
)
from ..cli._shared import _load_or_exit, _parse_repo

reference_app = typer.Typer(
    name="reference",
    help="Manage reference repo indexes for cross-repo dependency checking.",
    no_args_is_help=True,
)


def _resolve_repo_targets(repo: Optional[str], all_flag: bool, config) -> list[str]:
    if all_flag:
        targets = config.reference_repos
        if not targets:
            display_error("No reference repos configured. Set reference.repos in config.yml")
            raise typer.Exit(1)
        return list(targets)
    if not repo:
        configured = ", ".join(config.reference_repos) or "(none)"
        display_error(f"Pass owner/repo or use --all. Configured repos: {configured}")
        raise typer.Exit(1)
    return [repo]


def _build_one(target: str, config) -> None:
    from ..integrations.github import GitHubClient
    from ..storage.reference import build_index, save_index
    from ..core.config import resolve_github_token

    owner, repo_name = _parse_repo(target)
    token = resolve_github_token(owner, config)
    github = GitHubClient(token)
    display_info(f"Building reference index for {target}…")
    try:
        index = build_index(owner, repo_name, github)
        path = save_index(index)
        display_success(
            f"Indexed {index.files_indexed} files · "
            f"{len(index.index):,} symbols → {path}"
        )
    finally:
        github.close()


@reference_app.command(name="build")
def reference_build(
    repo: Annotated[
        Optional[str],
        typer.Argument(help="Reference repo in owner/repo format."),
    ] = None,
    all_flag: Annotated[bool, typer.Option("--all", help="Build every configured reference repo.")] = False,
):
    """Build a reference repo index."""
    config = _load_or_exit()
    for target in _resolve_repo_targets(repo, all_flag, config):
        try:
            _build_one(target, config)
        except Exception as e:
            display_error(f"{target}: {e}")


@reference_app.command(name="refresh")
def reference_refresh(
    repo: Annotated[
        Optional[str],
        typer.Argument(help="Reference repo in owner/repo format."),
    ] = None,
    all_flag: Annotated[bool, typer.Option("--all", help="Refresh every configured reference repo.")] = False,
):
    """Refresh (rebuild) a reference repo index."""
    config = _load_or_exit()
    for target in _resolve_repo_targets(repo, all_flag, config):
        try:
            _build_one(target, config)
        except Exception as e:
            display_error(f"{target}: {e}")


@reference_app.command(name="status")
def reference_status():
    """Show status of all configured reference repos."""
    from ..storage.reference import load_index

    config = _load_or_exit()
    if not config.reference_repos:
        display_info("No reference repos configured. Set reference.repos in config.yml")
        return

    for target in config.reference_repos:
        try:
            owner, repo_name = _parse_repo(target)
        except Exception:
            display_info(f"{target:<40} ✗ malformed")
            continue
        try:
            index = load_index(owner, repo_name)
        except Exception as e:
            display_info(f"{target:<40} ✗ load failed: {e}")
            continue
        if not index:
            display_info(f"{target:<40} ✗ not built  (run: eagleeye reference build {target})")
            continue
        display_info(
            f"{target:<40} ✓ {index.built_at[:10]}  "
            f"{index.files_indexed} files  {len(index.index):,} symbols"
        )
