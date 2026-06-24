"""EagleEye MCP Server core — FastMCP instance and shared helpers."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP(
    "EagleEye",
    instructions=(
        "EagleEye gives you tools to fetch GitHub repository and pull request data. "
        "Use these tools to:\n"
        "- Review pull requests: call get_pull_request, then analyze the diff\n"
        "- Understand a repo: call get_repository_overview, then summarize\n"
        "- Find bugs: call get_pull_request or get_file_or_directory, then scan for issues\n"
        "- Generate diagrams: call generate_diagram with your analysis as input; "
        "pass diagram_format='drawio' for a draw.io XML diagram (dark navy + lime theme) "
        "or diagram_format='mermaid' (default) for a Mermaid diagram\n"
        "- Post results: call post_pr_comment with your review as markdown\n\n"
        "Always start by listing PRs with list_pull_requests if the user hasn't specified a PR number."
    ),
)


def _get_github_client():
    """Get a GitHub client, raising a clear error if token is missing."""
    from eagleeye.integrations.github import GitHubClient

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_TOKEN is not set. Add it to the MCP server environment config."
        )
    return GitHubClient(token)


def _parse_repo(repo: str) -> tuple[str, str]:
    parts = repo.strip().split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Invalid repo format '{repo}'. Use 'owner/repo'.")
    return parts[0], parts[1]


def run():
    """Entry point for the eagleeye-mcp script."""
    mcp.run()


# Register tools via side-effect imports
from eagleeye.servers.mcp import tools as _tools  # noqa: E402, F401
