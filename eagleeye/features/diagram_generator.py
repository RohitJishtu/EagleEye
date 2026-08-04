"""Diagram Generator feature: produce Mermaid diagrams from repo analysis and PR reviews."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from ..core.config import EagleEyeConfig
from ..core.models import DiagramResult, PRReviewResult, RepoSummaryResult
from ..core.prompt_loader import get_prompt
from ..integrations.anthropic.client import AIClient, _clean_json

_DIAGRAM_SCHEMA = json.dumps(DiagramResult.model_json_schema(), sort_keys=True)


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
    client = _make_ai_client(config)
    summary_text = (
        f"Repository: {repo_name}\n"
        f"Purpose: {summary.purpose}\n"
        f"Tech Stack: {', '.join(summary.tech_stack)}\n\n"
        f"Architecture Layers:\n"
        + "\n".join(
            f"  - {layer.name}: {layer.description} (files: {', '.join(layer.key_files[:5])})"
            for layer in summary.architecture_layers
        )
        + f"\n\nEntry Points: {', '.join(summary.entry_points)}"
        + f"\nExternal Dependencies: {', '.join(summary.external_dependencies)}"
    )

    user_content = [
        client._make_content_block(
            "Generate a Mermaid architecture diagram for this repository.\n\n"
            f"{summary_text}\n\n"
            "Create a flowchart TD showing the major components, their relationships, "
            "and data flow.\n"
            "Use subgraphs for logical layers. Annotate edges with relationship types.\n"
            "Keep it readable: max 20 nodes.\n\n"
            f"Respond with valid JSON exactly matching this schema:\n{_DIAGRAM_SCHEMA}"
        )
    ]

    raw = client._call(get_prompt("utils.diagram"), user_content, max_tokens=4096)
    try:
        return DiagramResult.model_validate_json(_clean_json(raw))
    except (ValueError, ValidationError) as exc:
        raise RuntimeError(
            f"Claude returned an unexpected response: {raw[:200]!r}"
        ) from exc


def generate_change_impact_diagram(
    review: PRReviewResult,
    diff: str,
    repo_name: str,
    pr_title: str,
    config: EagleEyeConfig,
) -> DiagramResult:
    """Generate a Mermaid change-impact diagram from a PR review."""
    client = _make_ai_client(config)
    changed_files = [
        line[6:]
        for line in diff.splitlines()
        if line.startswith("--- a/") and not line.startswith("--- a/dev/null")
    ][:20]

    review_text = (
        f"Repository: {repo_name}\n"
        f"PR: {pr_title}\n"
        f"Risk Level: {review.risk_level}\n"
        f"Verdict: {review.overall_verdict}\n\n"
        f"Files Changed: {', '.join(changed_files)}\n\n"
        f"Summary: {review.summary}\n\n"
        f"Blocking Issues: {'; '.join(review.blocking_issues) or 'none'}\n\n"
        f"File Comments:\n"
        + "\n".join(
            f"  [{c.severity.upper()}] {c.file}: {c.comment}"
            for c in review.file_comments[:15]
        )
    )

    user_content = [
        client._make_content_block(
            f"Generate a Mermaid change-impact diagram for this pull request.\n\n{review_text}\n\n"
            f"Create a flowchart LR showing: which files changed → what they interact with → "
            f"downstream affected components.\n"
            f"Highlight changed nodes with style fill:#f90,color:#000.\n"
            f"Mark high/critical issues in red (style fill:#d00,color:#fff).\n\n"
            f"Respond with valid JSON exactly matching this schema:\n{_DIAGRAM_SCHEMA}"
        )
    ]

    raw = client._call(get_prompt("utils.diagram"), user_content, max_tokens=4096)
    try:
        return DiagramResult.model_validate_json(_clean_json(raw))
    except (ValueError, ValidationError) as exc:
        raise RuntimeError(
            f"Claude returned an unexpected response: {raw[:200]!r}"
        ) from exc


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
