"""Repository audit and data-flow analysis MCP tools."""

from __future__ import annotations

import fnmatch
import re
from typing import Optional

from ..server import _get_github_client, _parse_repo, mcp

# File patterns that reveal data flow in pipelines
_DATA_FLOW_PATTERNS = [
    # Orchestration
    "*.dag.py", "dags/*.py", "airflow/*.py",
    "flows/*.py", "pipelines/*.py",
    "dagster.yaml", "dagster/*.py", "definitions.py",
    "prefect.yaml", "prefect/*.py",
    # dbt
    "dbt_project.yml", "models/**/*.sql", "models/**/*.yml",
    "sources.yml", "schema.yml",
    # Spark / Databricks
    "jobs/*.py", "notebooks/*.py", "*.py",
    "cicd/*.yml", "cicd/*.yaml",
    ".github/workflows/*.yml",
    # Config / schema
    "config/*.yaml", "config/*.yml", "config/*.json",
    "schemas/*.json", "schemas/*.yaml",
    # Kafka / streaming
    "kafka/*.py", "streaming/*.py", "producers/*.py", "consumers/*.py",
]

_DATA_FLOW_KEYWORDS = re.compile(
    r'(spark|kafka|snowflake|delta|parquet|bronze|silver|gold|dbt|airflow|'
    r'dagster|prefect|pipeline|ingest|transform|sink|source|stream|batch|'
    r'read\.format|write\.format|\.load\(|\.save\(|createOrReplace|'
    r'merge into|insert into|copy into)',
    re.IGNORECASE,
)


@mcp.tool()
def analyze_data_flow(repo: str, branch: Optional[str] = None) -> str:
    """Fetch pipeline and data flow files from a repository for analysis and diagramming.

    Specifically targets orchestration files, Spark jobs, dbt models, Kafka producers/consumers,
    schema definitions, and CI/CD pipeline configs — the files that reveal how data moves
    through the system from source to sink.

    Use this to:
    - Map data sources → ingestion → transformation → storage → consumption
    - Identify pipeline dependencies and job ordering
    - Generate a data flow diagram (Mermaid or draw.io via generate_diagram)
    - Spot missing error handling, schema drift, or gaps in the pipeline

    After fetching, analyze the files and call generate_diagram with diagram_type='data_flow'.
    Pass diagram_format='drawio' to produce a draw.io XML diagram following the project
    design rules (dark navy + lime theme, swimlane stages, orthogonal edges).
    Pass diagram_format='mermaid' (default) for a flowchart LR diagram showing:
    - Data sources (databases, APIs, Kafka topics, files) as stadium shapes
    - Pipeline stages as subgraphs (Ingest, Transform, Load, Serve)
    - Data stores (Snowflake tables, Delta tables, S3 paths) as rounded rectangles
    - Job dependencies as annotated edges

    Args:
        repo: Repository in 'owner/repo' format
        branch: Branch to analyze (defaults to default branch)
    """
    owner, repo_name = _parse_repo(repo)
    github = _get_github_client()

    try:
        repo_meta = github.get_repo_metadata(owner, repo_name)
        effective_branch = branch or repo_meta.get("default_branch", "main")
        tree = github.get_repo_tree(owner, repo_name, effective_branch)
    except Exception as e:
        return f"Failed to fetch repo tree: {e}"
    finally:
        github.close()

    all_paths = [item["path"] for item in tree if item.get("type") == "blob"]

    # Select files matching data flow patterns
    selected = []
    seen = set()
    for pattern in _DATA_FLOW_PATTERNS:
        for path in all_paths:
            if path in seen:
                continue
            filename = path.split("/")[-1]
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(filename, pattern):
                selected.append(path)
                seen.add(path)
        if len(selected) >= 25:
            break

    # Fetch file contents, prioritise files with pipeline keywords
    github = _get_github_client()
    file_contents: dict[str, str] = {}
    total_bytes = 0
    _MAX_BYTES = 80_000

    try:
        for path in selected:
            if total_bytes >= _MAX_BYTES:
                break
            try:
                content = github.get_file_content(owner, repo_name, path, ref=effective_branch)
                # Skip files with no pipeline-relevant content
                if not _DATA_FLOW_KEYWORDS.search(content[:2000]):
                    continue
                chunk = content[:6_000]
                file_contents[path] = chunk
                total_bytes += len(chunk)
            except Exception:
                pass
    finally:
        github.close()

    if not file_contents:
        return (
            f"No data pipeline files found in {repo}.\n\n"
            f"Tip: This tool looks for Spark jobs, dbt models, Airflow DAGs, "
            f"Kafka producers/consumers, and pipeline config files. "
            f"If your pipeline uses a different structure, use get_file_or_directory "
            f"to fetch specific files manually."
        )

    # Build structured output for Claude to analyze
    files_section = "\n\n".join(
        f"### {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )

    return (
        f"# Data Flow Analysis: {repo}\n\n"
        f"**Branch:** `{effective_branch}`\n"
        f"**Pipeline files found:** {len(file_contents)}\n\n"
        f"---\n\n"
        f"## Instructions for Analysis\n\n"
        f"Analyze the files below and produce:\n"
        f"1. **Data flow summary** — sources, transformations, sinks, job dependencies\n"
        f"2. **Diagram** — call generate_diagram(diagram_type='data_flow', context=<summary>, "
        f"diagram_format='drawio') for a draw.io diagram, or diagram_format='mermaid' for "
        f"a Mermaid flowchart LR. drawio follows the project design rules (dark navy + lime "
        f"theme, swimlane stages, orthogonal edges).\n"
        f"3. **Risk flags** — missing error handling, schema drift, no idempotency, "
        f"missing data quality checks\n\n"
        f"---\n\n"
        f"## Pipeline Files\n\n"
        f"{files_section}"
    )


@mcp.tool()
def run_repo_health_check(repo: str, branch: Optional[str] = None, path: Optional[str] = None) -> str:
    """Run deterministic health checks across a repository or specific path.

    Scans files for known anti-patterns without needing AI — fast and reliable.
    Checks for:
    - Integer overflow (.cast("int") on large-range fields)
    - SQL injection (f-string SQL construction)
    - CI/CD silent failures (fail_on_run_failure: false on prerequisite jobs)
    - Hardcoded personal emails in CI/CD notifications
    - Schema drift risk (mergeSchema: true left on permanently)
    - Hardcoded secrets (tokens, passwords, API keys)
    - Swallowed exceptions in pipeline code

    After getting results, analyze findings and suggest which ones to prioritize fixing.

    Args:
        repo: Repository in 'owner/repo' format
        branch: Branch to scan (defaults to default branch)
        path: Optional subdirectory to limit the scan (e.g. 'src/' or 'cicd/')
    """
    from eagleeye.features.repo_auditor import run_audit

    owner, repo_name = _parse_repo(repo)
    github = _get_github_client()

    try:
        repo_meta = github.get_repo_metadata(owner, repo_name)
        effective_branch = branch or repo_meta.get("default_branch", "main")
        tree = github.get_repo_tree(owner, repo_name, effective_branch)
    except Exception as e:
        return f"Failed to fetch repo tree: {e}"
    finally:
        github.close()

    # Filter to relevant file types, optionally scoped to a path
    scannable = {".py", ".yml", ".yaml", ".sql", ".json"}
    all_paths = [
        item["path"] for item in tree
        if item.get("type") == "blob"
        and any(item["path"].endswith(ext) for ext in scannable)
        and (not path or item["path"].startswith(path.rstrip("/")))
    ][:60]  # cap at 60 files

    # Fetch file contents
    github = _get_github_client()
    file_contents: dict[str, str] = {}
    try:
        for file_path in all_paths:
            try:
                content = github.get_file_content(owner, repo_name, file_path, ref=effective_branch)
                file_contents[file_path] = content[:20_000]
            except Exception:
                pass
    finally:
        github.close()

    if not file_contents:
        return f"No scannable files found in {repo} (path={path or 'root'})."

    # Run audit
    result = run_audit(file_contents, repo=repo)

    if not result.findings:
        return (
            f"## Repo Health Check: {repo}\n\n"
            f"**No issues found** across {result.files_checked} files scanned.\n\n"
            f"Files scanned: {', '.join(list(file_contents.keys())[:10])}"
            + (" ..." if len(file_contents) > 10 else "")
        )

    # Format findings
    lines = [
        f"## Repo Health Check: {repo}",
        f"",
        f"**{result.summary()}**",
        f"Branch: `{effective_branch}` | Files scanned: {result.files_checked}",
        f"",
        f"---",
        f"",
    ]

    for f in result.findings:
        severity_icon = {"critical": "🚨", "high": "🔴", "medium": "🟡", "low": "🟢"}.get(f.severity, "⚪")
        lines += [
            f"### {severity_icon} [{f.severity.upper()}] {f.title}",
            f"**File:** `{f.file}`" + (f" (line {f.line})" if f.line else ""),
            f"**Checker:** {f.checker} | **Category:** {f.category}",
            f"",
            f"{f.description}",
            f"",
            f"**Fix:** {f.fix}",
            f"",
            f"---",
            f"",
        ]

    lines += [
        f"## Summary",
        f"| Severity | Count |",
        f"|---|---|",
        f"| 🚨 Critical | {result.critical_count} |",
        f"| 🔴 High | {result.high_count} |",
        f"| 🟡 Medium | {sum(1 for f in result.findings if f.severity == 'medium')} |",
        f"| 🟢 Low | {sum(1 for f in result.findings if f.severity == 'low')} |",
        f"| **Total** | **{len(result.findings)}** |",
    ]

    return "\n".join(lines)
