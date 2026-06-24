"""Main review/read/scan/list-prs/serve/cockpit commands (registered onto app in main.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..presentation.terminal import (
    console,
    display_agent_breakdown,
    display_batch_summary,
    display_bug_scan,
    display_diagram,
    display_error,
    display_info,
    display_pr_review,
    display_repo_summary,
    display_schema_impact,
    display_success,
    display_token_usage,
    display_warning,
)
from ..cli._shared import _load_or_exit, _parse_repo, _parse_github_url, _enable_debug

_DIAGRAMS_DIR = Path("eagleeye-diagrams")


def review(
    repo: Annotated[str, typer.Argument(help="GitHub repo ('owner/repo') or full GitHub PR URL")],
    pr_number: Annotated[Optional[int], typer.Argument(help="Pull request number (omit when passing a full URL)")] = None,
    post: Annotated[bool, typer.Option("--post", help="Post review as a GitHub PR comment")] = False,
    diagram: Annotated[bool, typer.Option("--diagram", help="Generate change-impact Mermaid diagram")] = False,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output format: json")] = None,
    usage: Annotated[bool, typer.Option("--usage", help="Show token usage and cache savings after review")] = False,
    context: Annotated[Optional[str], typer.Option("--context", help="Comma-separated owner/repo slugs to inject as context")] = None,
    agents: Annotated[bool, typer.Option("--agents", help="Show per-agent findings before synthesis")] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Re-raise exceptions with full stack trace instead of one-line error")] = False,
    debug_cache: Annotated[bool, typer.Option("--debug-cache", hidden=True)] = False,
):
    """Review a pull request with AI — get structured feedback, risk level, and blocking issues.

    Accepts either:
      eagleeye review owner/repo 42
      eagleeye review https://github.com/owner/repo/pull/42
    """
    if debug_cache:
        _enable_debug()

    config = _load_or_exit()

    parsed_url = _parse_github_url(repo)
    if parsed_url:
        owner, repo_name, pr_number = parsed_url
    else:
        owner, repo_name = _parse_repo(repo)
        if pr_number is None:
            display_error("Provide a PR number or pass a full GitHub PR URL.")
            raise typer.Exit(1)

    from ..features.pr_review import run_pr_review

    context_repos = [r.strip() for r in context.split(",")] if context else None
    try:
        result, diff, token_usage, schema_impact, pr_metadata = run_pr_review(
            owner, repo_name, pr_number, post, config, context_repos=context_repos
        )
    except Exception as e:
        if debug:
            raise
        display_error(str(e))
        raise typer.Exit(1)

    if agents:
        display_agent_breakdown(pr_metadata.get("agent_results", []))

    if output == "json":
        console.print_json(result.model_dump_json())
    else:
        pr_url = f"https://github.com/{owner}/{repo_name}/pull/{pr_number}"
        pr_info = {
            "number": pr_number,
            "title": pr_metadata.get("title", ""),
            "owner_repo": f"{owner}/{repo_name}",
        }
        display_pr_review(result, pr_url, pr_info=pr_info)
        if schema_impact:
            display_schema_impact(schema_impact)

    if usage:
        display_token_usage(token_usage)

    if diagram:
        from ..features.diagram_generator import generate_change_impact_diagram, save_diagram

        display_info("Generating change-impact diagram…")
        try:
            pr_meta_title = f"PR #{pr_number}"
            diagram_result = generate_change_impact_diagram(
                result, diff, f"{owner}/{repo_name}", pr_meta_title, config
            )
            out_dir = _DIAGRAMS_DIR / f"{owner}-{repo_name}"
            path = save_diagram(diagram_result, out_dir, f"pr-{pr_number}-change-impact")
            display_diagram(diagram_result, path)
        except Exception as e:
            display_warning(f"Diagram generation failed: {e}")


def read(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
    branch: Annotated[Optional[str], typer.Option("--branch", "-b", help="Branch to analyze")] = None,
    diagram: Annotated[bool, typer.Option("--diagram", help="Generate architecture Mermaid diagram")] = False,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output format: json")] = None,
    usage: Annotated[bool, typer.Option("--usage", help="Show token usage and cache savings after analysis")] = False,
    save_context: Annotated[bool, typer.Option("--save-context", help="Save this repo's summary as context for future reviews")] = False,
    debug_cache: Annotated[bool, typer.Option("--debug-cache", hidden=True)] = False,
):
    """Analyze a repo's architecture and produce an onboarding summary."""
    if debug_cache:
        _enable_debug()

    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    from ..features.repo_reader import run_repo_reader

    try:
        summary, repo_url, token_usage, file_tree = run_repo_reader(owner, repo_name, branch, config)
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)

    if output == "json":
        console.print_json(summary.model_dump_json())
    else:
        display_repo_summary(summary, repo_url)

    if usage:
        display_token_usage(token_usage)

    if save_context:
        from ..storage.context import save_context as store_context
        ctx_path = store_context(owner, repo_name, summary, file_tree)
        display_success(f"Context saved: {ctx_path}")

    if diagram:
        from ..features.diagram_generator import generate_architecture_diagram, save_diagram

        display_info("Generating architecture diagram…")
        try:
            diagram_result = generate_architecture_diagram(summary, f"{owner}/{repo_name}", config)
            out_dir = _DIAGRAMS_DIR / f"{owner}-{repo_name}"
            path = save_diagram(diagram_result, out_dir, "architecture")
            display_diagram(diagram_result, path)
        except Exception as e:
            display_warning(f"Diagram generation failed: {e}")


def read_all(
    owner: Annotated[str, typer.Argument(help="GitHub org or user name")],
    repos: Annotated[
        Optional[str],
        typer.Option("--repos", help="Comma-separated repo names to include (omit for all)"),
    ] = None,
    topic: Annotated[
        Optional[str],
        typer.Option("--topic", help="Filter repos by topic (e.g. 'data', 'ml', 'pipeline')"),
    ] = None,
    diagram: Annotated[bool, typer.Option("--diagram", help="Generate architecture diagram per repo")] = False,
    skip_forks: Annotated[bool, typer.Option("--skip-forks/--include-forks")] = True,
    skip_archived: Annotated[bool, typer.Option("--skip-archived/--include-archived")] = True,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output format: json")] = None,
):
    """Batch-analyze multiple repos under an org or user. Great for data project portfolios."""
    config = _load_or_exit()

    from ..features.diagram_generator import generate_architecture_diagram, save_diagram
    from ..features.repo_reader import run_repo_reader
    from ..integrations.github import GitHubClient

    github = GitHubClient(config.github_token)

    display_info(f"Listing repos for {owner}…")
    try:
        all_repos = github.list_org_repos(owner)
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)
    finally:
        github.close()

    if skip_forks:
        all_repos = [r for r in all_repos if not r.get("fork")]
    if skip_archived:
        all_repos = [r for r in all_repos if not r.get("archived")]
    if repos:
        wanted = {r.strip() for r in repos.split(",")}
        all_repos = [r for r in all_repos if r["name"] in wanted]
    if topic:
        all_repos = [r for r in all_repos if topic.lower() in [t.lower() for t in r.get("topics", [])]]

    if not all_repos:
        display_warning("No repos matched the filters.")
        raise typer.Exit(0)

    console.print(f"\n[bold]Analyzing {len(all_repos)} repo(s) under {owner}…[/bold]\n")

    summaries = []
    errors = []

    for repo_info in all_repos:
        repo_name = repo_info["name"]
        console.rule(f"[cyan]{owner}/{repo_name}[/cyan]")
        try:
            summary, repo_url, _, _ft = run_repo_reader(owner, repo_name, None, config)

            diagram_path = None
            if diagram:
                display_info("Generating architecture diagram…")
                try:
                    diagram_result = generate_architecture_diagram(
                        summary, f"{owner}/{repo_name}", config
                    )
                    out_dir = _DIAGRAMS_DIR / owner / repo_name
                    diagram_path = save_diagram(diagram_result, out_dir, "architecture")
                    display_diagram(diagram_result, diagram_path)
                except Exception as de:
                    display_warning(f"Diagram failed for {repo_name}: {de}")
            else:
                display_repo_summary(summary, repo_url)

            summaries.append((f"{owner}/{repo_name}", summary, diagram_path))

        except Exception as e:
            display_warning(f"Failed to analyze {repo_name}: {e}")
            errors.append(repo_name)

    console.rule()

    if output == "json":
        out = [
            {"repo": name, "summary": s.model_dump()}
            for name, s, _ in summaries
        ]
        console.print_json(json.dumps(out))
    else:
        display_batch_summary(summaries)

    if errors:
        display_warning(f"Failed repos: {', '.join(errors)}")


def scan(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
    pr: Annotated[Optional[int], typer.Option("--pr", help="PR number to scan")] = None,
    path: Annotated[Optional[str], typer.Option("--path", help="File or directory path in the repo")] = None,
    branch: Annotated[Optional[str], typer.Option("--branch", "-b", help="Branch for path scanning")] = None,
    severity: Annotated[str, typer.Option("--severity", help="Minimum severity: critical|high|medium|low")] = "low",
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output format: json")] = None,
    usage: Annotated[bool, typer.Option("--usage", help="Show token usage and cache savings after scan")] = False,
    debug_cache: Annotated[bool, typer.Option("--debug-cache", hidden=True)] = False,
):
    """Deep security and bug scan of a PR diff or repo path."""
    if debug_cache:
        _enable_debug()

    if not pr and not path:
        display_error("Provide either --pr <number> or --path <path>.")
        raise typer.Exit(1)

    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    from ..features.bug_scanner import run_path_bug_scan, run_pr_bug_scan

    try:
        if pr:
            result, token_usage = run_pr_bug_scan(owner, repo_name, pr, config)
        else:
            result, token_usage = run_path_bug_scan(owner, repo_name, path, branch, config)
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)

    # Apply severity filter
    severity_order = ["critical", "high", "medium", "low"]
    min_idx = severity_order.index(severity) if severity in severity_order else 3
    result.findings = [
        f for f in result.findings
        if severity_order.index(f.severity) <= min_idx if f.severity in severity_order
    ]
    if output == "json":
        console.print_json(result.model_dump_json())
    else:
        display_bug_scan(result)

    if usage:
        display_token_usage(token_usage)


def list_prs(
    repo: Annotated[str, typer.Argument(help="GitHub repo in owner/repo format")],
):
    """List open pull requests in a repo — quick lookup before running review or scan."""
    config = _load_or_exit()
    owner, repo_name = _parse_repo(repo)

    from rich import box
    from rich.table import Table

    from ..integrations.github import GitHubClient

    github = GitHubClient(config.github_token)
    try:
        prs = github.list_open_prs(owner, repo_name)
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)
    finally:
        github.close()

    if not prs:
        console.print(f"[dim]No open PRs in {owner}/{repo_name}.[/dim]")
        return

    table = Table(
        title=f"Open PRs — {owner}/{repo_name}",
        box=box.ROUNDED,
        show_lines=False,
    )
    table.add_column("#", width=6, style="bold cyan")
    table.add_column("Title", max_width=60)
    table.add_column("Author", width=18, style="dim")
    table.add_column("Updated", width=12, style="dim")
    table.add_column("Draft", width=6)

    for pr in prs:
        updated = pr.get("updated_at", "")[:10]
        draft = "[yellow]draft[/yellow]" if pr.get("draft") else ""
        table.add_row(str(pr["number"]), pr["title"], pr["author"], updated, draft)

    console.print(table)


def serve(
    host: Annotated[str, typer.Option("--host", help="Bind host")] = "0.0.0.0",
    port: Annotated[int, typer.Option("--port", "-p", help="Bind port")] = 8080,
    reload: Annotated[bool, typer.Option("--reload", help="Auto-reload on code changes (dev)")] = False,
    secret: Annotated[Optional[str], typer.Option("--secret", help="GitHub webhook secret (overrides GITHUB_WEBHOOK_SECRET env var)")] = None,
):
    """Start the EagleEye webhook server for GitHub pull_request events.

    Configure your GitHub repo webhook to POST pull_request events to:
      http://your-host:<port>/webhook/github

    Set GITHUB_WEBHOOK_SECRET (or --secret) to validate HMAC-SHA256 signatures.
    Reviews are posted back to GitHub automatically when --post is enabled.
    """
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        display_error("fastapi and uvicorn are required. Run: pip install 'eagleeye[webhook]'")
        raise typer.Exit(1)

    if secret:
        import os
        os.environ["GITHUB_WEBHOOK_SECRET"] = secret

    _load_or_exit()  # validate config before starting
    display_info(f"Starting EagleEye webhook server on {host}:{port}…")
    display_info("Listening for pull_request.opened / synchronize / reopened events.")

    from ..webhook.server import run_server
    run_server(host=host, port=port, reload=reload)
