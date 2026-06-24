"""LangGraph wiring for the multi-agent PR review workflow."""

from __future__ import annotations

from collections import deque
from typing import Any

from langgraph.graph import END, StateGraph

from ...integrations.anthropic.client import TokenUsage
from ...core.config import resolve_github_token
from ...core.models import PRReviewResult
from .._shared import make_llm
from .nodes import (
    node_arch_drift_agent,
    node_lineage_agent,
    node_pr_agent,
    node_reference_agent,
    node_schema_agent,
    synthesize_findings,
)
from .prepare import prepare_agent_input
from .state import MultiAgentReviewState

_AGENT_NODES = ["pr_agent", "schema_agent", "lineage_agent", "reference_agent", "arch_drift_agent"]


def fetch_pr_data(state: MultiAgentReviewState) -> dict:
    from ..pr_review import fetch_pr_data as _fetch
    return _fetch(state)  # type: ignore[arg-type]


def fetch_file_contents(state: MultiAgentReviewState) -> dict:
    from ..pr_review import fetch_file_contents as _fetch
    return _fetch(state)  # type: ignore[arg-type]


def fetch_base_files_and_diff_symbols(state: MultiAgentReviewState) -> dict:
    from ..pr_review import fetch_base_files_and_diff_symbols as _fetch
    return _fetch(state)  # type: ignore[arg-type]


def fetch_cross_repo_callers(state: MultiAgentReviewState) -> dict:
    from ..pr_review import fetch_cross_repo_callers as _fetch
    return _fetch(state)  # type: ignore[arg-type]


def post_github_comment(state: MultiAgentReviewState) -> dict:
    from ..pr_review import post_github_comment as _post
    return _post(state)  # type: ignore[arg-type]


def save_review_file(state: MultiAgentReviewState) -> dict:
    from ..pr_review import save_review_file as _save
    return _save(state)  # type: ignore[arg-type]


def _build_graph():
    g = StateGraph(MultiAgentReviewState)

    g.add_node("fetch_pr_data", fetch_pr_data)
    g.add_node("fetch_file_contents", fetch_file_contents)
    g.add_node("fetch_base_files_and_diff_symbols", fetch_base_files_and_diff_symbols)
    g.add_node("fetch_cross_repo_callers", fetch_cross_repo_callers)
    g.add_node("prepare_agent_input", prepare_agent_input)
    g.add_node("pr_agent", node_pr_agent)
    g.add_node("schema_agent", node_schema_agent)
    g.add_node("lineage_agent", node_lineage_agent)
    g.add_node("reference_agent", node_reference_agent)
    g.add_node("arch_drift_agent", node_arch_drift_agent)
    g.add_node("synthesize_findings", synthesize_findings)
    g.add_node("post_github_comment", post_github_comment)
    g.add_node("save_review_file", save_review_file)

    g.set_entry_point("fetch_pr_data")
    g.add_edge("fetch_pr_data", "fetch_file_contents")
    g.add_edge("fetch_file_contents", "fetch_base_files_and_diff_symbols")
    g.add_edge("fetch_base_files_and_diff_symbols", "fetch_cross_repo_callers")
    g.add_edge("fetch_cross_repo_callers", "prepare_agent_input")

    for node in _AGENT_NODES:
        g.add_edge("prepare_agent_input", node)

    for node in _AGENT_NODES:
        g.add_edge(node, "synthesize_findings")

    g.add_edge("synthesize_findings", "post_github_comment")
    g.add_edge("post_github_comment", "save_review_file")
    g.add_edge("save_review_file", END)
    return g.compile()


_graph = _build_graph()


def run_multi_agent_pr_review_graph(
    owner: str,
    repo: str,
    pr_number: int,
    post_comment: bool,
    config,
    context_repos=None,
) -> tuple[PRReviewResult, str, TokenUsage, Any, dict]:
    initial: MultiAgentReviewState = {
        "owner": owner,
        "repo": repo,
        "pr_number": pr_number,
        "post_comment": post_comment,
        "api_key": config.anthropic_api_key,
        "github_token": resolve_github_token(owner, config),
        "github_tokens": config.github_tokens,
        "model": config.model,
        "max_tokens": config.max_tokens,
        "auth_mode": config.auth_mode,
        "proxy_client_id": config.proxy_client_id,
        "proxy_client_secret": config.proxy_client_secret,
        "proxy_url": config.proxy_url,
        "token_url": config.token_url,
        "scope": config.scope,
        "max_files": config.max_files,
        "max_file_bytes": config.max_file_bytes,
        "max_total_bytes": config.max_total_bytes,
        "diff": "",
        "pr_metadata": {},
        "file_list": [],
        "full_file_contents": {},
        "files_fetched": 0,
        "files_total": 0,
        "file_manifest": [],
        "search_window": deque(),
        "agent_input": None,
        "pr_agent_input": None,
        "schema_agent_input": None,
        "lineage_agent_input": None,
        "reference_agent_input": None,
        "reference_repos": config.reference_repos,
        "arch_drift_input": None,
        "synthesis_input": None,
        "agent_results": [],
        "raw_usage": [],
        "result": None,
        "schema_impact": None,
        "context_repos": context_repos or [],
        "token_usage": TokenUsage(),
        "error": None,
    }
    llm = make_llm(initial)
    final = _graph.invoke(initial, config={"configurable": {"llm": llm}})
    pr_meta = dict(final.get("pr_metadata", {}))
    pr_meta["agent_results"] = final.get("agent_results", [])
    return final["result"], final["diff"], final["token_usage"], final["schema_impact"], pr_meta
