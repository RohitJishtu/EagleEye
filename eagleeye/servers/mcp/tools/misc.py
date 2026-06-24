"""Diagram generation, scheduling, and webhook status MCP tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..server import _parse_repo, mcp

# Load draw.io design rules (eagleeye-diagrams/rules.txt lives next to the package root)
_RULES_FILE = Path(__file__).parent.parent.parent.parent.parent / "eagleeye-diagrams" / "rules.txt"
try:
    _DRAWIO_RULES = _RULES_FILE.read_text()
except FileNotFoundError:
    _DRAWIO_RULES = ""


@mcp.tool()
def generate_diagram(
    diagram_type: str,
    context: str,
    title: Optional[str] = None,
    diagram_format: str = "mermaid",
) -> str:
    """Generate a diagram based on analysis context.

    Call this after analyzing a repo or PR to produce a visual diagram.
    Supports two output formats:
      - 'mermaid': lightweight Mermaid source, renders on GitHub / VS Code.
      - 'drawio': draw.io XML following project design rules (dark navy + lime theme,
        swimlane stages, orthogonal edges). Open via File → Open from Device in
        app.diagrams.net — never via URL or VS Code.

    Args:
        diagram_type: 'architecture' (repo analysis), 'data_flow', or 'change_impact' (PR review)
        context: Summary of the analysis — architecture layers, changed files, data flows, etc.
        title: Optional title for the diagram
        diagram_format: 'mermaid' (default) or 'drawio'
    """
    diagram_title = title or (
        "Architecture Diagram" if diagram_type == "architecture"
        else "Data Flow Diagram" if diagram_type == "data_flow"
        else "Change Impact Diagram"
    )

    if diagram_format == "drawio":
        rules_section = (
            f"\n\n## DESIGN RULES (mandatory — do not deviate)\n\n{_DRAWIO_RULES}\n"
            if _DRAWIO_RULES
            else ""
        )
        if diagram_type in ("architecture", "data_flow"):
            type_instructions = (
                "Generate a draw.io architecture/data-flow diagram.\n"
                "- Use swimlane containers for pipeline stages (Ingest, Transform, Load, Serve)\n"
                "- Pipeline flows top-to-bottom in the left column\n"
                "- External storage (databases, APIs, queues) in the middle column as cylinders\n"
                "- ML lifecycle / consumers in the far-right column\n"
                "- All edges orthogonal with explicit exitX/exitY/entryX/entryY for cross-container edges\n"
                "- No edge text labels\n"
            )
        else:
            type_instructions = (
                "Generate a draw.io change-impact diagram.\n"
                "- Use swimlane containers for affected layers\n"
                "- Changed nodes: fillColor=#b3ff47;fontColor=#000000\n"
                "- Critical/high severity nodes: fillColor=#d00000;fontColor=#ffffff\n"
                "- All edges orthogonal with explicit exitX/exitY/entryX/entryY for cross-container edges\n"
                "- No edge text labels\n"
            )
        return (
            f"Generate a draw.io '{diagram_type}' diagram titled '{diagram_title}'.\n\n"
            f"{type_instructions}"
            f"{rules_section}\n"
            f"Context to diagram:\n\n{context}\n\n"
            "Return ONLY the raw draw.io XML (<mxGraphModel> ... </mxGraphModel>), "
            "no markdown fences, no commentary. The user will open it via "
            "File → Open from Device in app.diagrams.net."
        )

    # --- Mermaid (default) ---
    if diagram_type == "architecture":
        instructions = (
            "Generate a Mermaid flowchart TD (top-down) architecture diagram.\n"
            "- Use subgraphs for logical layers (e.g. Ingestion, Transform, Storage)\n"
            "- Annotate edges with relationship types: calls, reads, writes, triggers\n"
            "- Show external systems (databases, APIs, queues) as stadium shapes\n"
            "- Keep it under 20 nodes for readability\n"
            "- Return ONLY the raw Mermaid source, no backtick fences\n\n"
        )
    elif diagram_type == "data_flow":
        instructions = (
            "Generate a Mermaid flowchart LR (left-right) data flow diagram.\n"
            "- Stadium shapes ([Source]) for external sources (Kafka, S3, APIs, DBs)\n"
            "- Subgraphs for pipeline stages: Ingest, Transform, Load, Serve\n"
            "- Rounded rectangles (Table) for data stores (Snowflake, Delta, Bronze/Silver/Gold)\n"
            "- Annotated edges: reads, writes, triggers, merges, streams\n"
            "- Return ONLY the raw Mermaid source, no backtick fences\n\n"
        )
    else:
        instructions = (
            "Generate a Mermaid flowchart LR (left-right) change-impact diagram.\n"
            "- Highlight changed files/modules with: style NodeId fill:#f90,color:#000\n"
            "- Mark critical/high severity issues in red: style NodeId fill:#d00,color:#fff\n"
            "- Show downstream affected components\n"
            "- Annotate edges with the type of relationship\n"
            "- Return ONLY the raw Mermaid source, no backtick fences\n\n"
        )

    return (
        f"Generate a {diagram_type} Mermaid diagram titled '{diagram_title}'.\n\n"
        f"{instructions}"
        f"Context to diagram:\n\n{context}\n\n"
        f"Return the Mermaid source wrapped in triple backticks with 'mermaid' language tag "
        f"so it renders on GitHub."
    )


@mcp.tool()
def schedule_review(
    repo: str,
    cron: str = "0 * * * *",
    post_comment: bool = True,
) -> str:
    """Schedule automated review of new PRs in a repository.

    The scheduler checks for unreviewed open PRs on the given cron schedule
    and automatically reviews them. Results are saved locally and optionally
    posted to GitHub.

    Args:
        repo: Repository in 'owner/repo' format.
        cron: 5-field cron expression (default: hourly '0 * * * *').
        post_comment: Post the review as a GitHub PR comment (default True).
    """
    try:
        from eagleeye.scheduler.runner import add_scheduled_repo
    except ImportError:
        return "apscheduler is not installed. Run: pip install 'eagleeye[scheduler]'"

    owner, repo_name = _parse_repo(repo)
    try:
        job_id = add_scheduled_repo(owner, repo_name, cron, post_comment)
        return (
            f"Scheduled automated review for **{repo}**.\n\n"
            f"- Job ID: `{job_id}`\n"
            f"- Cron: `{cron}`\n"
            f"- Post comment: {post_comment}\n\n"
            f"Use `eagleeye schedule list` in the CLI to manage scheduled repos."
        )
    except Exception as exc:
        return f"Failed to schedule review for {repo}: {exc}"


@mcp.tool()
def webhook_status() -> str:
    """Check whether the EagleEye webhook server is running and show scheduled review jobs.

    Pings the local webhook server health endpoint and lists all cron-scheduled repos.
    """
    import httpx as _httpx

    webhook_url = os.environ.get("EAGLEEYE_WEBHOOK_URL", "http://localhost:8080")
    server_status = "unknown"
    try:
        resp = _httpx.get(f"{webhook_url}/health", timeout=3.0)
        server_status = "running ✅" if resp.is_success else f"error (HTTP {resp.status_code})"
    except Exception:
        server_status = "not reachable — start with `eagleeye serve`"

    jobs_text = "(apscheduler not installed)"
    try:
        from eagleeye.scheduler.runner import list_scheduled_repos
        jobs = list_scheduled_repos()
        jobs_text = (
            "\n".join(f"- `{j['job_id']}` — next run: {j['next_run']}" for j in jobs)
            or "(none scheduled)"
        )
    except ImportError:
        pass

    return (
        f"## EagleEye Webhook & Scheduler Status\n\n"
        f"**Webhook server** ({webhook_url}): {server_status}\n\n"
        f"**Scheduled repos:**\n{jobs_text}\n\n"
        f"To start: `eagleeye serve`\n"
        f"To add a schedule: `eagleeye schedule add owner/repo`"
    )
