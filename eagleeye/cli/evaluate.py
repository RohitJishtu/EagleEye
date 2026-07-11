"""eagleeye evaluate — one-command repo evaluation with scorecard and saved report."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from ..presentation.terminal import (
    display_error,
    display_repo_evaluation,
    display_token_usage,
)
from ..features.repo_evaluate import run_repo_evaluate
from ._shared import _load_or_exit, _parse_repo


def evaluate(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
    branch: Annotated[Optional[str], typer.Option("--branch", "-b", help="Branch to evaluate")] = None,
    path: Annotated[Optional[str], typer.Option("--path", help="Subdirectory scope (e.g. core/)")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Deterministic audit only (no Anthropic key)")] = False,
    no_deep_scan: Annotated[bool, typer.Option("--no-deep-scan", help="Reserved: skip deep LLM bug scan (Sprint 2)")] = False,
    include_data_dirs: Annotated[bool, typer.Option(
        "--include-data-dirs",
        help="Include data/ and out/ in LLM payload (may contain PII)",
    )] = False,
    usage: Annotated[bool, typer.Option("--usage", help="Show token usage after evaluation")] = False,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output format: json")] = None,
):
    """Evaluate a repository — understanding, security, secrets/PII, ratings, and saved report.

    One command produces an executive assessment similar to eagleeye review for PRs.
    """
    _ = no_deep_scan  # Sprint 2: wire bug_scanner deep pass
    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    try:
        result, token_usage, saved_path = run_repo_evaluate(
            owner,
            repo_name,
            config,
            branch=branch,
            scoped_path=path,
            no_llm=no_llm,
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
