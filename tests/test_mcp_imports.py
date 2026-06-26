"""Smoke tests for MCP server imports and tool registration."""

import os

import pytest

EXPECTED_TOOLS = {
    "list_pull_requests",
    "get_pull_request",
    "get_repository_overview",
    "get_file_or_directory",
    "post_pr_comment",
    "approve_pull_request",
    "request_changes_pull_request",
    "save_review",
    "list_reviews",
    "get_review",
    "analyze_data_flow",
    "run_repo_health_check",
    "generate_diagram",
    "schedule_review",
    "webhook_status",
}


@pytest.fixture(autouse=True)
def _github_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", os.environ.get("GITHUB_TOKEN", "ghp_test_token"))


def test_mcp_server_run_importable():
    from eagleeye.mcp_server import run

    assert callable(run)


def test_mcp_server_entry_point_matches_shim():
    from eagleeye.mcp_server import run as shim_run
    from eagleeye.servers.mcp.server import run as server_run

    assert shim_run is server_run


def test_mcp_tools_registered():
    from eagleeye.servers.mcp.server import mcp

    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert registered == EXPECTED_TOOLS
