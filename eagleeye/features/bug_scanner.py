"""Bug Scanner feature: deep security and logic bug analysis of PR diffs or repo paths."""

from __future__ import annotations

from typing import Optional

from ..integrations.anthropic.client import TokenUsage
from ..core.config import EagleEyeConfig
from ..core.models import BugScanResult


def run_pr_bug_scan(
    owner: str,
    repo: str,
    pr_number: int,
    config: EagleEyeConfig,
) -> tuple[BugScanResult, TokenUsage]:
    """Scan a PR diff for bugs and security issues."""
    from ..graphs.bug_scanner import run_bug_scan_graph

    return run_bug_scan_graph(owner=owner, repo=repo, pr_number=pr_number, config=config)


def run_path_bug_scan(
    owner: str,
    repo: str,
    path: str,
    branch: Optional[str],
    config: EagleEyeConfig,
) -> tuple[BugScanResult, TokenUsage]:
    """Scan a file or directory in a repo for bugs and security issues."""
    from ..graphs.bug_scanner import run_bug_scan_graph

    return run_bug_scan_graph(owner=owner, repo=repo, path=path, branch=branch, config=config)
