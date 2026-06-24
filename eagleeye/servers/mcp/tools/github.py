"""GitHub data-fetching and PR interaction MCP tools."""

from __future__ import annotations

import fnmatch
from typing import Optional

from ..server import _get_github_client, _parse_repo, mcp

_PRIORITY_PATTERNS = [
    "README.md", "README.rst", "readme.md",
    "pyproject.toml", "setup.py", "package.json", "Cargo.toml", "go.mod",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".github/workflows/*.yml", ".github/workflows/*.yaml",
    "dbt_project.yml", "airflow_settings.yaml", "dagster.yaml", "prefect.yaml",
    "main.py", "app.py", "index.js", "index.ts",
    "src/main.*", "src/app.*", "src/index.*",
    "config/*.py", "config/*.yaml", "config/*.yml",
    "docs/ARCHITECTURE.md", "docs/architecture.md",
]


def _select_key_files(all_paths: list[str], max_files: int = 10) -> list[str]:
    selected, seen = [], set()
    for pattern in _PRIORITY_PATTERNS:
        if len(selected) >= max_files:
            break
        for path in all_paths:
            if path in seen:
                continue
            filename = path.split("/")[-1]
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(filename, pattern):
                selected.append(path)
                seen.add(path)
                if len(selected) >= max_files:
                    break
    return selected


@mcp.tool()
def list_pull_requests(repo: str) -> str:
    """List all open pull requests in a GitHub repository.

    Use this first to find PR numbers before calling get_pull_request.

    Args:
        repo: Repository in 'owner/repo' format (e.g. 'myorg/myrepo')
    """
    owner, repo_name = _parse_repo(repo)
    github = _get_github_client()

    try:
        prs = github.list_open_prs(owner, repo_name)
    finally:
        github.close()

    if not prs:
        return f"No open pull requests found in {repo}."

    lines = [f"Open PRs in {repo} ({len(prs)} total):\n"]
    for pr in prs:
        draft = " [DRAFT]" if pr.get("draft") else ""
        updated = pr.get("updated_at", "")[:10]
        lines.append(
            f"  PR #{pr['number']}{draft} — {pr['title']}\n"
            f"    Author: {pr['author']}  |  Updated: {updated}\n"
            f"    URL: {pr['html_url']}"
        )
    return "\n".join(lines)


@mcp.tool()
def get_pull_request(repo: str, pr_number: int) -> str:
    """Fetch the full diff, metadata, and complete file contents of a pull request.

    Returns the unified diff PLUS the full content of each changed file so you
    can cross-reference type definitions, schemas, and dependencies across files.
    Use this data to:
    - Perform a deep code review (cross-file type mismatches, schema vs cast errors)
    - Check CI/CD job dependency chains (fail_on_run_failure, job ordering)
    - Scan for critical vulnerabilities
    - Generate a change-impact diagram

    Args:
        repo: Repository in 'owner/repo' format
        pr_number: The pull request number
    """
    owner, repo_name = _parse_repo(repo)

    # Load file limits from config
    from eagleeye.core.config import load_config as _load_config
    _cfg = _load_config()
    max_files = _cfg.max_files
    max_file_bytes = _cfg.max_file_bytes
    max_total_bytes = _cfg.max_total_bytes

    github = _get_github_client()

    try:
        diff = github.get_pr_diff(owner, repo_name, pr_number)
        meta = github.get_pr_metadata(owner, repo_name, pr_number)
        files = github.get_pr_files(owner, repo_name, pr_number)
        repo_meta = github.get_repo_metadata(owner, repo_name)
        effective_branch = (
            meta.get("head_sha")
            or repo_meta.get("default_branch", "main")
        )

        # Fetch full content of changed files for cross-file analysis
        full_file_contents: dict[str, str] = {}
        total_bytes = 0

        for f in files[:max_files]:
            if total_bytes >= max_total_bytes:
                break
            try:
                content = github.get_file_content(
                    owner, repo_name, f["filename"], ref=effective_branch
                )
                chunk = content[:max_file_bytes]
                full_file_contents[f["filename"]] = chunk
                total_bytes += len(chunk)
            except Exception:
                pass
    finally:
        github.close()

    file_list = [f["filename"] for f in files]
    additions = sum(f.get("additions", 0) for f in files)
    deletions = sum(f.get("deletions", 0) for f in files)

    # Blast radius: structural analysis of changed Python symbols and their callers.
    from eagleeye.analysis import compute_blast_radius, format_as_markdown

    blast = compute_blast_radius(diff, full_file_contents)
    blast_section = format_as_markdown(blast)

    # Truncate diff if very large
    diff_preview = diff
    if len(diff) > 80_000:
        diff_preview = diff[:80_000] + f"\n\n... [diff truncated — {len(diff)//1024}KB total]"

    # Build full file contents section
    full_files_section = "\n\n".join(
        f"### {path}\n```\n{content}\n```"
        + (f"\n_(truncated to {max_file_bytes // 1_000}KB)_" if len(content) >= max_file_bytes else "")
        for path, content in full_file_contents.items()
    )

    # Estimate tokens in the data payload sent to Claude (~4 chars per token)
    diff_tokens = len(diff_preview) // 4
    files_tokens = sum(len(c) for c in full_file_contents.values()) // 4
    total_tokens = diff_tokens + files_tokens

    # Estimate manual review time: 2 min per file + 1 min per 50 lines changed
    total_lines = additions + deletions
    manual_minutes = (len(file_list) * 2) + (total_lines // 50)
    manual_minutes = max(manual_minutes, 10)  # minimum 10 min

    # Manual Claude (copy-paste) would need ~2-3x tokens since no automated fetching
    manual_claude_tokens = total_tokens * 2

    context_stats = (
        f"## EagleEye Review Stats\n\n"
        f"**Data fetched for this review:**\n\n"
        f"| What | Size | Est. tokens |\n"
        f"|---|---|---|\n"
        f"| Diff (+{additions} / -{deletions} lines) | {len(diff_preview):,} chars | ~{diff_tokens:,} |\n"
        f"| Full file contents ({len(full_file_contents)} files) | "
        f"{sum(len(c) for c in full_file_contents.values()):,} chars | ~{files_tokens:,} |\n"
        f"| **Total** | | **~{total_tokens:,} tokens** |\n\n"
        f"**Approach comparison:**\n\n"
        f"| Approach | Time | Token cost | Cross-file analysis |\n"
        f"|---|---|---|---|\n"
        f"| Manual repo review | ~{manual_minutes} min | $0 but engineer time | ❌ Easy to miss |\n"
        f"| Claude (manual copy-paste) | ~{manual_minutes // 2} min | ~{manual_claude_tokens:,} tokens | ⚠️ Only what you paste |\n"
        f"| **EagleEye + Claude** | **~1 min** | **~{total_tokens:,} tokens** | **✅ Automated** |\n\n"
        f"_Include this table in your review summary._"
    )

    return (
        f"# PR #{pr_number}: {meta['title']}\n\n"
        f"**Repository:** {repo}\n"
        f"**Author:** {meta['author']}\n"
        f"**Base branch:** {meta['base']}\n"
        f"**URL:** {meta['html_url']}\n\n"
        f"**Description:**\n{meta['body'] or '(no description provided)'}\n\n"
        f"**Changed files ({len(file_list)}) — +{additions} / -{deletions} lines:**\n"
        + "\n".join(f"  - {f}" for f in file_list)
        + f"\n\n---\n\n## Diff\n\n```diff\n{diff_preview}\n```"
        + f"\n\n---\n\n## Full File Contents (for cross-file analysis)\n\n"
        + (full_files_section or "(no file contents fetched)")
        + f"\n\n---\n\n{blast_section}"
        + f"\n\n---\n\n{context_stats}"
    )


@mcp.tool()
def get_repository_overview(repo: str, branch: Optional[str] = None) -> str:
    """Fetch a comprehensive overview of a GitHub repository for architectural analysis.

    Returns the README, file tree, and contents of up to 10 key files
    (config files, entrypoints, build files). Use this to:
    - Summarize what the repo does and how it's structured
    - Generate an architecture or data flow diagram
    - Create onboarding documentation
    - Understand a data pipeline or ML project

    Args:
        repo: Repository in 'owner/repo' format
        branch: Branch to analyze (defaults to the repo's default branch)
    """
    owner, repo_name = _parse_repo(repo)
    github = _get_github_client()

    try:
        repo_meta = github.get_repo_metadata(owner, repo_name)
        effective_branch = branch or repo_meta.get("default_branch", "main")

        readme = github.get_repo_readme(owner, repo_name)

        try:
            tree = github.get_repo_tree(owner, repo_name, effective_branch)
        except Exception:
            tree = []

        all_paths = [item["path"] for item in tree if item.get("type") == "blob"]
        key_paths = _select_key_files(all_paths)

        key_files: dict[str, str] = {}
        for path in key_paths:
            try:
                content = github.get_file_content(owner, repo_name, path, ref=effective_branch)
                key_files[path] = content[:5_000]
            except Exception:
                pass
    finally:
        github.close()

    # Build file tree string (compact)
    tree_lines = [item["path"] for item in tree[:300] if item.get("type") == "blob"]
    tree_str = "\n".join(f"  {p}" for p in tree_lines)
    if len(tree) > 300:
        tree_str += f"\n  ... ({len(tree) - 300} more files)"

    key_files_section = "\n\n".join(
        f"### {path}\n```\n{content}\n```"
        for path, content in key_files.items()
    )

    return (
        f"# Repository: {repo_meta.get('full_name', repo)}\n\n"
        f"**Description:** {repo_meta.get('description') or '(none)'}\n"
        f"**Primary Language:** {repo_meta.get('language') or 'Unknown'}\n"
        f"**Topics:** {', '.join(repo_meta.get('topics', [])) or 'none'}\n"
        f"**Default branch:** {effective_branch}\n\n"
        f"---\n\n"
        f"## README\n\n{readme or '(no README found)'}\n\n"
        f"---\n\n"
        f"## File Tree\n\n{tree_str}\n\n"
        f"---\n\n"
        f"## Key Files\n\n{key_files_section or '(no key files found)'}"
    )


@mcp.tool()
def get_file_or_directory(repo: str, path: str, branch: Optional[str] = None) -> str:
    """Fetch the content of a specific file or directory in a GitHub repository.

    Use this for deep bug scanning of a specific module, security audit of
    an auth layer, or reviewing a data pipeline component.

    Args:
        repo: Repository in 'owner/repo' format
        path: File path (e.g. 'src/auth.py') or directory path (e.g. 'src/auth/')
        branch: Branch to read from (defaults to default branch)
    """
    owner, repo_name = _parse_repo(repo)
    github = _get_github_client()

    try:
        repo_meta = github.get_repo_metadata(owner, repo_name)
        effective_branch = branch or repo_meta.get("default_branch", "main")

        # Try as a file first
        try:
            content = github.get_file_content(owner, repo_name, path, ref=effective_branch)
            return (
                f"# File: {path}\n"
                f"**Repo:** {repo}  |  **Branch:** {effective_branch}\n\n"
                f"```\n{content[:80_000]}\n```"
                + ("\n\n_(file truncated)_" if len(content) > 80_000 else "")
            )
        except Exception:
            pass

        # Try as a directory
        tree = github.get_repo_tree(owner, repo_name, effective_branch)
        dir_files = [
            item["path"] for item in tree
            if item.get("type") == "blob"
            and item["path"].startswith(path.rstrip("/") + "/")
        ][:20]

        if not dir_files:
            return f"No files found at path '{path}' in {repo} on branch {effective_branch}."

        parts = []
        total = 0
        for file_path in dir_files:
            try:
                fc = github.get_file_content(owner, repo_name, file_path, ref=effective_branch)
                chunk = f"### {file_path}\n```\n{fc[:8_000]}\n```"
                parts.append(chunk)
                total += len(chunk)
                if total > 80_000:
                    parts.append("_(remaining files omitted — content limit reached)_")
                    break
            except Exception:
                pass

        return (
            f"# Directory: {path}\n"
            f"**Repo:** {repo}  |  **Branch:** {effective_branch}\n"
            f"**Files ({len(dir_files)}):** {', '.join(dir_files)}\n\n"
            + "\n\n".join(parts)
        )
    finally:
        github.close()


@mcp.tool()
def post_pr_comment(repo: str, pr_number: int, comment: str) -> str:
    """Post a review comment to a GitHub pull request.

    Use this after completing a code review or bug scan to share findings
    directly on the PR. Format the comment as markdown for best readability.

    Args:
        repo: Repository in 'owner/repo' format
        pr_number: The pull request number
        comment: The markdown-formatted comment body to post
    """
    owner, repo_name = _parse_repo(repo)
    github = _get_github_client()

    try:
        # Append EagleEye attribution
        full_comment = comment.rstrip()
        if "EagleEye" not in full_comment:
            full_comment += "\n\n---\n_Posted by EagleEye via Claude_"

        github.post_pr_comment(owner, repo_name, pr_number, full_comment)
    finally:
        github.close()

    return f"Comment posted to {repo} PR #{pr_number}."


@mcp.tool()
def approve_pull_request(repo: str, pr_number: int, message: str) -> str:
    """Approve a GitHub pull request with a formal review.

    IMPORTANT: You MUST ask the user for explicit confirmation before calling this tool.
    Show the review findings first, then ask: "Should I approve this PR?"
    Only call this tool after the user says yes.

    Args:
        repo: Repository in 'owner/repo' format
        pr_number: The pull request number
        message: Approval message summarising why the PR is approved
    """
    owner, repo_name = _parse_repo(repo)
    github = _get_github_client()

    try:
        full_message = message.rstrip()
        if "EagleEye" not in full_message:
            full_message += "\n\n---\n_Reviewed and approved by EagleEye via Claude_"
        github.submit_pr_review(owner, repo_name, pr_number, "APPROVE", full_message)
    finally:
        github.close()

    return f"PR #{pr_number} in {repo} has been approved."


@mcp.tool()
def request_changes_pull_request(repo: str, pr_number: int, message: str) -> str:
    """Request changes on a GitHub pull request with a formal review.

    IMPORTANT: You MUST ask the user for explicit confirmation before calling this tool.
    Show the review findings first, then ask: "Should I request changes on this PR?"
    Only call this tool after the user says yes.

    Args:
        repo: Repository in 'owner/repo' format
        pr_number: The pull request number
        message: Markdown-formatted summary of required changes
    """
    owner, repo_name = _parse_repo(repo)
    github = _get_github_client()

    try:
        full_message = message.rstrip()
        if "EagleEye" not in full_message:
            full_message += "\n\n---\n_Reviewed by EagleEye via Claude_"
        github.submit_pr_review(owner, repo_name, pr_number, "REQUEST_CHANGES", full_message)
    finally:
        github.close()

    return f"Changes requested on PR #{pr_number} in {repo}."
