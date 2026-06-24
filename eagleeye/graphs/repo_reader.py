"""LangGraph workflow for repo reading — replaces AIClient.summarize_repo()."""

from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from ..integrations.anthropic.client import (
    _REPO_SUMMARY_SCHEMA,
    TokenUsage,
    _clean_json,
)
from ..core.models import RepoSummaryResult
from ..core.prompt_loader import get_prompt
from ..workflows.repo_read.helpers import (
    _MAX_FILE_BYTES,
    _build_tree_string,
    _select_key_files,
)


class RepoReaderState(TypedDict):
    # Inputs
    owner: str
    repo: str
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
    repo_metadata: dict
    repo_url: str
    effective_branch: str
    readme: str
    file_tree: list[dict]
    file_tree_str: str
    key_paths: list[str]
    key_file_contents: dict[str, str]
    # Output
    result: Optional[RepoSummaryResult]
    token_usage: TokenUsage



def fetch_repo_metadata(state: RepoReaderState) -> dict:
    from ..presentation.terminal import display_info
    from ..integrations.github import GitHubClient

    display_info(f"Fetching repo metadata for {state['owner']}/{state['repo']}…")
    github = GitHubClient(state["github_token"])
    meta = github.get_repo_metadata(state["owner"], state["repo"])
    github.close()

    repo_url = meta.get("html_url", f"https://github.com/{state['owner']}/{state['repo']}")
    effective_branch = state.get("branch") or meta.get("default_branch", "main")
    return {"repo_metadata": meta, "repo_url": repo_url, "effective_branch": effective_branch}


def fetch_readme_and_tree(state: RepoReaderState) -> dict:
    from ..presentation.terminal import display_info
    from ..integrations.github import GitHubAPIError, GitHubClient

    display_info("Fetching README and file tree…")
    github = GitHubClient(state["github_token"])
    readme = github.get_repo_readme(state["owner"], state["repo"])
    try:
        tree = github.get_repo_tree(state["owner"], state["repo"], state["effective_branch"])
    except GitHubAPIError:
        tree = []
    github.close()

    return {
        "readme": readme,
        "file_tree": tree,
        "file_tree_str": _build_tree_string(tree),
    }


def select_and_fetch_key_files(state: RepoReaderState) -> dict:
    from ..presentation.terminal import display_info
    from ..integrations.github import GitHubClient

    all_paths = [item["path"] for item in state["file_tree"] if item.get("type") == "blob"]
    key_paths = _select_key_files(all_paths)

    display_info(f"Fetching {len(key_paths)} key files…")
    github = GitHubClient(state["github_token"])
    key_file_contents: dict[str, str] = {}
    for path in key_paths:
        try:
            content = github.get_file_content(
                state["owner"], state["repo"], path, ref=state["effective_branch"]
            )
            key_file_contents[path] = content[:_MAX_FILE_BYTES]
        except Exception:
            pass
    github.close()

    return {"key_paths": key_paths, "key_file_contents": key_file_contents}


def analyze_repo(state: RepoReaderState) -> dict:
    from langchain_core.messages import HumanMessage
    from pydantic import ValidationError

    from ..presentation.terminal import display_info
    from ._shared import accumulate_usage, make_cached_system_message, make_content_block, make_llm

    display_info("Analyzing with Claude…")
    llm = make_llm(state)
    system = make_cached_system_message(get_prompt("utils.repo_reader"))

    repo_meta = state["repo_metadata"]
    meta_block = (
        f"## Repository Metadata\n"
        f"Name: {repo_meta.get('full_name', '')}\n"
        f"Description: {repo_meta.get('description', '')}\n"
        f"Primary Language: {repo_meta.get('language', '')}\n"
        f"Topics: {', '.join(repo_meta.get('topics', []))}\n\n"
        f"## README\n\n{state['readme'] or '(no README found)'}"
    )

    key_files_text = "\n\n".join(
        f"### {path}\n```\n{content[:5000]}\n```"
        for path, content in state["key_file_contents"].items()
    )

    user_blocks = [
        make_content_block(meta_block, cache=True),
        make_content_block(f"## File Tree\n\n{state['file_tree_str']}", cache=True),
        make_content_block(
            f"## Key File Contents\n\n{key_files_text}"
            if key_files_text
            else "## Key File Contents\n\n(none)"
        ),
        make_content_block(
            f"Respond with valid JSON exactly matching this schema:\n{_REPO_SUMMARY_SCHEMA}"
        ),
    ]

    response = llm.invoke([system, HumanMessage(content=user_blocks)])

    usage = state.get("token_usage") or TokenUsage()
    accumulate_usage(usage, response.response_metadata)

    raw = response.content if isinstance(response.content, str) else str(response.content)
    try:
        result = RepoSummaryResult.model_validate_json(_clean_json(raw))
    except (ValueError, ValidationError) as exc:
        raise RuntimeError(f"Claude returned unexpected response: {raw[:200]!r}") from exc

    return {"result": result, "token_usage": usage}



def _build_graph():
    g = StateGraph(RepoReaderState)
    g.add_node("fetch_repo_metadata", fetch_repo_metadata)
    g.add_node("fetch_readme_and_tree", fetch_readme_and_tree)
    g.add_node("select_and_fetch_key_files", select_and_fetch_key_files)
    g.add_node("analyze_repo", analyze_repo)
    g.set_entry_point("fetch_repo_metadata")
    g.add_edge("fetch_repo_metadata", "fetch_readme_and_tree")
    g.add_edge("fetch_readme_and_tree", "select_and_fetch_key_files")
    g.add_edge("select_and_fetch_key_files", "analyze_repo")
    g.add_edge("analyze_repo", END)
    return g.compile()


_graph = _build_graph()


def run_repo_reader_graph(
    owner: str,
    repo: str,
    branch,
    config,
) -> tuple[RepoSummaryResult, str, TokenUsage, list[dict]]:
    initial: RepoReaderState = {
        "owner": owner,
        "repo": repo,
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
        "repo_metadata": {},
        "repo_url": "",
        "effective_branch": "",
        "readme": "",
        "file_tree": [],
        "file_tree_str": "",
        "key_paths": [],
        "key_file_contents": {},
        "result": None,
        "token_usage": TokenUsage(),
    }
    final = _graph.invoke(initial)
    return final["result"], final["repo_url"], final["token_usage"], final.get("file_tree", [])
