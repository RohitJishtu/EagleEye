"""Diagram Generator feature: produce Mermaid diagrams from repo analysis and PR reviews."""

from __future__ import annotations

from pathlib import Path

from ..integrations.anthropic.client import AIClient, TokenUsage
from ..core.config import EagleEyeConfig
from ..core.models import DiagramResult, PRReviewResult, RepoSummaryResult


def _make_ai_client(config: EagleEyeConfig) -> AIClient:
    return AIClient(
        config.anthropic_api_key,
        config.model,
        config.max_tokens,
        auth_mode=config.auth_mode,
        proxy_client_id=config.proxy_client_id,
        proxy_client_secret=config.proxy_client_secret,
        proxy_url=config.proxy_url,
        token_url=config.token_url,
        scope=config.scope,
    )


def generate_architecture_diagram(
    summary: RepoSummaryResult,
    repo_name: str,
    config: EagleEyeConfig,
) -> DiagramResult:
    """Generate a Mermaid architecture diagram from a repo summary."""
    return _make_ai_client(config).generate_architecture_diagram(summary, repo_name)


def generate_change_impact_diagram(
    review: PRReviewResult,
    diff: str,
    repo_name: str,
    pr_title: str,
    config: EagleEyeConfig,
) -> DiagramResult:
    """Generate a Mermaid change-impact diagram from a PR review."""
    return _make_ai_client(config).generate_change_impact_diagram(review, diff, repo_name, pr_title)


def save_diagram(result: DiagramResult, output_dir: Path, filename: str) -> Path:
    """Save a diagram as both a .mmd file and a .md file with mermaid fencing.

    Returns the path to the .mmd file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    mmd_path = output_dir / f"{filename}.mmd"
    md_path = output_dir / f"{filename}.md"

    mmd_path.write_text(result.mermaid_source, encoding="utf-8")

    md_content = (
        f"# {result.title}\n\n"
        f"_{result.description}_\n\n"
        f"```mermaid\n{result.mermaid_source}\n```\n"
    )
    md_path.write_text(md_content, encoding="utf-8")

    return mmd_path
