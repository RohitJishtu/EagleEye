"""eagleeye evaluate — one-command repo evaluation with multi-module deep read."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from ..features.repo_evaluate import run_repo_evaluate
from ..presentation.terminal import (
    display_error,
    display_repo_evaluation,
    display_token_usage,
)
from ._shared import _load_or_exit, _parse_repo


def evaluate(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
    branch: Annotated[
        Optional[str],
        typer.Option("--branch", "-b", help="Branch to evaluate"),
    ] = None,
    path: Annotated[
        Optional[str],
        typer.Option("--path", help="Subdirectory scope (e.g. core/)"),
    ] = None,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Deterministic audit only (no Anthropic key)"),
    ] = False,
    quick: Annotated[bool, typer.Option(
        "--quick",
        help="Skip multi-module deep-read; single-pass synthesis on key files only",
    )] = False,
    no_deep_scan: Annotated[bool, typer.Option(
        "--no-deep-scan",
        help="Alias for --quick (skip multi-module deep-read)",
    )] = False,
    include_data_dirs: Annotated[bool, typer.Option(
        "--include-data-dirs",
        help="Include data/ and out/ in LLM payload (may contain PII)",
    )] = False,
    usage: Annotated[
        bool,
        typer.Option("--usage", help="Show token usage after evaluation"),
    ] = False,
    output: Annotated[
        Optional[str],
        typer.Option("--output", "-o", help="Output format: json"),
    ] = None,
):
    """Evaluate a repository — multi-module understanding, security, and saved report.

    By default deep-reads important modules then synthesizes one evaluation.
    Use --quick for the lighter single-pass path, or --no-llm for audit-only.
    """
    config = _load_or_exit(require_claude=not no_llm)
    owner, repo_name = _parse_repo(repo)
    use_quick = quick or no_deep_scan

    try:
        result, token_usage, saved_path = run_repo_evaluate(
            owner,
            repo_name,
            config,
            branch=branch,
            scoped_path=path,
            no_llm=no_llm,
            quick=use_quick,
            include_data_dirs=include_data_dirs,
        )
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)

    if output == "json":
        typer.echo(result.model_dump_json(indent=2))
    else:
        from pathlib import Path
        display_repo_evaluation(result, saved_path=Path(saved_path))

    if usage:
        display_token_usage(token_usage)
