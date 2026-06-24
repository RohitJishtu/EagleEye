"""Review persistence MCP tools."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from eagleeye.core.paths import reviews_dir, reviews_root

from ..server import _parse_repo, mcp


@mcp.tool()
def save_review(repo: str, pr_number: int, pr_title: str, review_content: str) -> str:
    """Save a PR review to a local markdown file in the reviews/ folder.

    Call this after completing a code review to persist it locally.
    The file is named after the PR title so it is easy to find later.

    Format the review_content with these sections in order:
    1. Header: PR title, Requested by (PR author @login), Repo, Date, URL
    2. Review verdict: "Okay to merge" | "Needs attention" | "Let's revisit" + Risk level
    3. Summary paragraph
    4. Findings (grouped by severity: CRITICAL → HIGH → MEDIUM), each as: description — file:line
    5. Blocking Issues (bullet list of must-fix items)
    6. Remediation Details (per finding: severity, location, explanation, fix suggestion)
    7. Feature Store Impact Analysis (if PR touches ML feature definitions or model registration jobs)
    8. EDP Impact Analysis (if PR touches Databricks jobs, dbt models, or Snowflake pipelines)
    9. Misc Issues (LOW and INFO severity items)
    10. Positive Highlights (what was done well)

    Args:
        repo: Repository in 'owner/repo' format (e.g. 'myorg/myrepo')
        pr_number: The pull request number
        pr_title: The PR title — used to name the file
        review_content: The full review in markdown format following the structure above
    """
    from eagleeye.features.pr_review import slugify_title
    slug = slugify_title(pr_title)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"pr-{pr_number}-{slug}.md"

    owner, repo_name = _parse_repo(repo)
    out_dir = reviews_dir(owner, repo_name)
    out_dir.mkdir(parents=True, exist_ok=True)

    filepath = out_dir / filename
    header = (
        f"---\n"
        f"repo: {repo}\n"
        f"pr: {pr_number}\n"
        f"title: {pr_title}\n"
        f"date: {date_str}\n"
        f"url: https://github.com/{repo}/pull/{pr_number}\n"
        f"---\n\n"
    )
    filepath.write_text(header + review_content.strip() + "\n")

    return f"Review saved to {filepath}"


@mcp.tool()
def list_reviews(repo: Optional[str] = None) -> str:
    """List all saved EagleEye reviews, optionally filtered by repo.

    Use this to find a past review before loading it with get_review.

    Args:
        repo: Optional repo in 'owner/repo' format to filter results.
              If omitted, lists reviews across all repos.
    """
    root = reviews_root()
    if not root.exists():
        return "No reviews saved yet. Run a PR review first."

    if repo:
        owner, repo_name = _parse_repo(repo)
        search_dirs = [reviews_dir(owner, repo_name)]
    else:
        search_dirs = [d for d in root.iterdir() if d.is_dir()]

    lines = []
    for d in sorted(search_dirs):
        md_files = sorted(d.glob("*.md"))
        if not md_files:
            continue
        lines.append(f"\n**{d.name}/**")
        for f in md_files:
            # Extract date and title from frontmatter if present
            text = f.read_text()
            date = next((l.split("date:")[1].strip() for l in text.splitlines() if l.startswith("date:")), "")
            title = next((l.split("title:")[1].strip() for l in text.splitlines() if l.startswith("title:")), f.stem)
            pr = next((l.split("pr:")[1].strip() for l in text.splitlines() if l.startswith("pr:")), "")
            lines.append(f"  - PR #{pr} ({date}) — {title}  →  `{f}`")

    if not lines:
        return "No reviews found."

    return "## Saved Reviews\n" + "\n".join(lines)


@mcp.tool()
def get_review(repo: str, pr_number: int) -> str:
    """Load a saved EagleEye review for follow-up discussion.

    Use this to retrieve a past review so you can:
    - Answer follow-up questions about specific findings
    - Check whether issues raised were addressed in a later PR
    - Compare findings across multiple PRs
    - Track which blocking issues were resolved

    Args:
        repo: Repository in 'owner/repo' format
        pr_number: The pull request number of the review to load
    """
    owner, repo_name = _parse_repo(repo)
    repo_reviews_dir = reviews_dir(owner, repo_name)

    if not repo_reviews_dir.exists():
        return f"No reviews found for {repo}. Run a PR review first."

    # Find file matching pr_number
    matches = list(repo_reviews_dir.glob(f"pr-{pr_number}-*.md"))
    if not matches:
        available = [f.name for f in sorted(repo_reviews_dir.glob("*.md"))]
        available_str = "\n".join(f"  - {f}" for f in available) or "  (none)"
        return (
            f"No review found for PR #{pr_number} in {repo}.\n\n"
            f"Available reviews:\n{available_str}"
        )

    content = matches[0].read_text()
    return (
        f"# Loaded Review: {matches[0].name}\n\n"
        f"{content}\n\n"
        f"---\n"
        f"_Review loaded from `{matches[0]}`. You can now ask follow-up questions about this review._"
    )
