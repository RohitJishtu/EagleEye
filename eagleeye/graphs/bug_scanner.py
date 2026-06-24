"""LangGraph workflow for bug scanning — replaces AIClient.scan_for_bugs()."""

from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from ..integrations.anthropic.client import (
    TokenUsage,
    _BUG_SCAN_SCHEMA,
    _clean_json,
)
from ..core.models import BugScanResult
from ..core.prompt_loader import get_prompt

_MAX_CONTENT_BYTES = 150_000


class BugScanState(TypedDict):
    # Inputs
    owner: str
    repo: str
    pr_number: Optional[int]
    path: Optional[str]
    branch: Optional[str]
    api_key: str
    github_token: str
    model: str
    max_tokens: int
    auth_mode: str
    proxy_client_id: str
    proxy_client_secret: str
    proxy_url: str
    token_url: str
    scope: str
    # Fetched
    content: str
    target_description: str
    scan_mode: str  # pr | file | directory
    # Output
    result: Optional[BugScanResult]
    token_usage: TokenUsage



def fetch_pr_content(state: BugScanState) -> dict:
    from ..presentation.terminal import display_info, display_warning
    from ..integrations.github import GitHubClient

    display_info(f"Fetching PR #{state['pr_number']} diff from {state['owner']}/{state['repo']}…")
    github = GitHubClient(state["github_token"])
    diff = github.get_pr_diff(state["owner"], state["repo"], state["pr_number"])
    metadata = github.get_pr_metadata(state["owner"], state["repo"], state["pr_number"])
    github.close()

    content = diff
    if len(content.encode()) > _MAX_CONTENT_BYTES:
        display_warning("Very large diff — truncating to 150 KB for analysis.")
        content = content.encode()[:_MAX_CONTENT_BYTES].decode("utf-8", errors="replace")

    target = (
        f"{state['owner']}/{state['repo']} PR #{state['pr_number']}: "
        f"{metadata.get('title', '')}"
    )
    return {"content": content, "target_description": target, "scan_mode": "pr"}


def fetch_path_content(state: BugScanState) -> dict:
    from ..presentation.terminal import display_info, display_warning
    from ..integrations.github import GitHubAPIError, GitHubClient

    github = GitHubClient(state["github_token"])
    repo_meta = github.get_repo_metadata(state["owner"], state["repo"])
    effective_branch = state.get("branch") or repo_meta.get("default_branch", "main")
    path = state["path"]

    display_info(f"Fetching content at {path} in {state['owner']}/{state['repo']}@{effective_branch}…")

    try:
        content = github.get_file_content(state["owner"], state["repo"], path, ref=effective_branch)
        scan_mode = "file"
    except GitHubAPIError:
        display_info("Path is a directory — fetching files…")
        tree = github.get_repo_tree(state["owner"], state["repo"], effective_branch)
        dir_files = [
            item["path"]
            for item in tree
            if item.get("type") == "blob"
            and item["path"].startswith(path.rstrip("/") + "/")
        ][:20]

        if not dir_files:
            github.close()
            raise ValueError(f"No files found at path '{path}' in {state['owner']}/{state['repo']}")

        parts = []
        total_bytes = 0
        for file_path in dir_files:
            try:
                file_content = github.get_file_content(
                    state["owner"], state["repo"], file_path, ref=effective_branch
                )
                chunk = f"### {file_path}\n```\n{file_content[:10_000]}\n```\n"
                if total_bytes + len(chunk.encode()) > _MAX_CONTENT_BYTES:
                    display_warning("Content limit reached — skipping remaining files.")
                    break
                parts.append(chunk)
                total_bytes += len(chunk.encode())
            except Exception:
                pass

        content = "\n".join(parts)
        scan_mode = "directory"

    github.close()
    target = f"{state['owner']}/{state['repo']} path: {path} (branch: {effective_branch})"
    return {"content": content, "target_description": target, "scan_mode": scan_mode}


def analyze_bugs(state: BugScanState) -> dict:
    from langchain_core.messages import HumanMessage
    from pydantic import ValidationError

    from ..presentation.terminal import display_info
    from ._shared import accumulate_usage, make_cached_system_message, make_content_block, make_llm

    display_info("Scanning with Claude…")
    llm = make_llm(state)
    system = make_cached_system_message(get_prompt("utils.bug_scanner"))

    content = state["content"]
    header = (
        f"Scan Mode: {state['scan_mode'].upper()}\n"
        f"Target: {state['target_description']}\n\n"
        f"## Content to Analyze\n\n{content}"
    )

    user_blocks = [
        make_content_block(header, cache=len(content.encode()) > 10_000),
        make_content_block(
            f"Respond with valid JSON exactly matching this schema:\n{_BUG_SCAN_SCHEMA}"
        ),
    ]

    response = llm.invoke([system, HumanMessage(content=user_blocks)])

    usage = state.get("token_usage") or TokenUsage()
    accumulate_usage(usage, response.response_metadata)

    raw = response.content if isinstance(response.content, str) else str(response.content)
    try:
        result = BugScanResult.model_validate_json(_clean_json(raw))
    except (ValueError, ValidationError) as exc:
        raise RuntimeError(f"Claude returned unexpected response: {raw[:200]!r}") from exc

    return {"result": result, "token_usage": usage}



def _route_entry(state: BugScanState) -> str:
    return "fetch_pr_content" if state.get("pr_number") is not None else "fetch_path_content"


def _build_graph():
    g = StateGraph(BugScanState)
    g.add_node("fetch_pr_content", fetch_pr_content)
    g.add_node("fetch_path_content", fetch_path_content)
    g.add_node("analyze_bugs", analyze_bugs)
    g.set_conditional_entry_point(
        _route_entry,
        {
            "fetch_pr_content": "fetch_pr_content",
            "fetch_path_content": "fetch_path_content",
        },
    )
    g.add_edge("fetch_pr_content", "analyze_bugs")
    g.add_edge("fetch_path_content", "analyze_bugs")
    g.add_edge("analyze_bugs", END)
    return g.compile()


_graph = _build_graph()


def run_bug_scan_graph(
    owner: str,
    repo: str,
    config,
    pr_number: Optional[int] = None,
    path: Optional[str] = None,
    branch: Optional[str] = None,
) -> tuple[BugScanResult, TokenUsage]:
    initial: BugScanState = {
        "owner": owner,
        "repo": repo,
        "pr_number": pr_number,
        "path": path,
        "branch": branch,
        "api_key": config.anthropic_api_key,
        "github_token": config.github_token,
        "model": config.model,
        "max_tokens": config.max_tokens,
        "auth_mode": config.auth_mode,
        "proxy_client_id": config.proxy_client_id,
        "proxy_client_secret": config.proxy_client_secret,
        "proxy_url": config.proxy_url,
        "token_url": config.token_url,
        "scope": config.scope,
        "content": "",
        "target_description": "",
        "scan_mode": "",
        "result": None,
        "token_usage": TokenUsage(),
    }
    final = _graph.invoke(initial)
    return final["result"], final["token_usage"]
