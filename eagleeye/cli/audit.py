"""eagleeye audit — deterministic repo health checks (no LLM)."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from ..presentation.terminal import display_audit, display_error, display_warning
from ..workflows.repo_audit import run_repo_audit
from ._shared import _load_or_exit, _parse_repo


def audit(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
    branch: Annotated[Optional[str], typer.Option("--branch", "-b", help="Branch to scan")] = None,
    path: Annotated[Optional[str], typer.Option("--path", help="Subdirectory to limit scan (e.g. cicd/)")] = None,
    severity: Annotated[str, typer.Option("--severity", help="Minimum severity: critical|high|medium|low")] = "low",
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output format: json")] = None,
):
    """Run fast deterministic health checks across a repo (secrets, SQL injection, CI anti-patterns).

    No AI required — uses pattern-based checkers from repo_auditor.
  """
    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    try:
        result, effective_branch, files_scanned, _coverage = run_repo_audit(
            owner, repo_name, config, branch=branch, path=path,
        )
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)

    if not files_scanned:
        display_warning(
            f"No scannable files found in {owner}/{repo_name} "
            f"(branch={effective_branch}, path={path or 'root'})."
        )
        raise typer.Exit(1)

    severity_order = ["critical", "high", "medium", "low"]
    min_idx = severity_order.index(severity) if severity in severity_order else 3
    filtered = [
        f for f in result.findings
        if f.severity in severity_order and severity_order.index(f.severity) <= min_idx
    ]
    result.findings = filtered

    if output == "json":
        import json
        payload = {
            "repo": result.repo,
            "branch": effective_branch,
            "files_checked": result.files_checked,
            "findings": [f.as_dict() for f in result.findings],
            "critical_count": result.critical_count,
            "high_count": result.high_count,
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        display_audit(result, branch=effective_branch, files_scanned=files_scanned)
