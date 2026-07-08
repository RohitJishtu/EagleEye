"""Tests for the multi-agent PR review graph."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from eagleeye.ai_client import TokenUsage
from eagleeye.models import (
    AgentFinding,
    AgentResult,
    FileComment,
    MultiAgentReviewInput,
    PRReviewResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_agent_input():
    return MultiAgentReviewInput(
        diff="diff --git a/foo.py b/foo.py\n+x = int(val)",
        pr_metadata={"title": "Test PR", "author": "alice", "base": "main", "body": ""},
        file_list=["foo.py"],
        full_file_contents={"foo.py": "x = int(val)\n"},
        blast_radius_md="## Blast Radius\n\nNo changed symbols.",
        schema_impact_md="## Schema Impact\n\nNo changes.",
        test_coverage_md="## Test Coverage\n\nNo gaps.",
        security_scan_md="## Security Scan\n\nNo issues.",
    )


@pytest.fixture
def sample_pr_result():
    return PRReviewResult(
        summary="Looks good.",
        overall_verdict="approve",
        risk_level="low",
        file_comments=[
            FileComment(
                file="foo.py",
                severity="low",
                category="style",
                comment="Minor style issue.",
            )
        ],
        positive_highlights=["Clean change"],
        blocking_issues=[],
    )


def _make_agent_result(agent: str, n_findings: int = 1) -> AgentResult:
    findings = [
        AgentFinding(
            agent=agent,
            file="foo.py",
            severity="low",
            category="style",
            title=f"Issue from {agent}",
            description="Some description.",
        )
        for _ in range(n_findings)
    ]
    return AgentResult(agent=agent, findings=findings, summary=f"{agent} summary")


# ---------------------------------------------------------------------------
# Unit tests: diff filtering helpers
# ---------------------------------------------------------------------------


def test_filter_diff_by_keywords_matches():
    from eagleeye.graphs.agent_inputs import _filter_diff_by_keywords

    diff = (
        "diff --git a/jobs/load_data.yml b/jobs/load_data.yml\n"
        "+on_failure:\n"
        "+  email: user@example.com\n"
        "diff --git a/src/app.py b/src/app.py\n"
        "+x = 1\n"
    )
    result = _filter_diff_by_keywords(diff, (".yml",))
    assert "load_data.yml" in result
    assert "app.py" not in result


def test_filter_diff_by_keywords_no_match():
    from eagleeye.graphs.agent_inputs import _filter_diff_by_keywords

    diff = "diff --git a/src/app.py b/src/app.py\n+x = 1\n"
    result = _filter_diff_by_keywords(diff, (".sql",))
    assert result == "(no relevant diff sections)"


def test_added_import_lines_extracts_correctly():
    from eagleeye.graphs.agent_inputs import _added_import_lines

    diff = (
        "+import os\n"
        "+from pathlib import Path\n"
        "+x = 1\n"
        "-import sys\n"
    )
    result = _added_import_lines(diff)
    assert "import os" in result
    assert "from pathlib import Path" in result
    assert "x = 1" not in result
    assert "import sys" not in result


# ---------------------------------------------------------------------------
# Unit tests: agent response parser
# ---------------------------------------------------------------------------


def test_parse_agent_response_object():
    from eagleeye.graphs.multi_agent_review import _parse_agent_response

    payload = {
        "agent": "pr",
        "findings": [
            {
                "file": "foo.py",
                "severity": "high",
                "category": "logic",
                "title": "Bug",
                "description": "A bug",
                "fix_suggestion": "Fix it",
            }
        ],
        "summary": "Found a bug",
    }
    result = _parse_agent_response(json.dumps(payload), "pr")
    assert result.agent == "pr"
    assert len(result.findings) == 1
    assert result.findings[0].severity == "high"
    assert result.summary == "Found a bug"


def test_parse_agent_response_bare_list():
    from eagleeye.graphs.multi_agent_review import _parse_agent_response

    payload = [
        {
            "file": "bar.py",
            "severity": "medium",
            "category": "security",
            "title": "Secret",
            "description": "Hardcoded secret",
        }
    ]
    result = _parse_agent_response(json.dumps(payload), "schema")
    assert result.agent == "schema"
    assert len(result.findings) == 1
    assert result.findings[0].agent == "schema"


def test_parse_agent_response_invalid_json():
    from eagleeye.graphs.multi_agent_review import _parse_agent_response

    result = _parse_agent_response("not json at all", "lineage")
    assert result.agent == "lineage"
    assert result.error is not None
    assert result.findings == []


def test_parse_agent_response_empty_findings():
    from eagleeye.graphs.multi_agent_review import _parse_agent_response

    payload = {"agent": "feature", "findings": [], "summary": "No issues"}
    result = _parse_agent_response(json.dumps(payload), "feature")
    assert result.findings == []
    assert result.error is None


# ---------------------------------------------------------------------------
# Integration-style tests: run_agents_parallel node
# ---------------------------------------------------------------------------


def _make_mock_llm_response(agent_name: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.content = json.dumps({"agent": agent_name, "findings": [], "summary": ""})
    mock_resp.response_metadata = {"usage": {}}
    return mock_resp


def test_all_five_node_agents_exist(sample_agent_input):
    """All 5 LangGraph node agent functions must exist and return agent_results."""
    from eagleeye.graphs.agent_inputs import slice_all
    from eagleeye.graphs.multi_agent_review import (
        node_pr_agent, node_schema_agent, node_lineage_agent,
        node_arch_drift_agent,
    )

    slices = slice_all(sample_agent_input)
    base_state = {
        "agent_input": sample_agent_input,
        "token_usage": TokenUsage(),
        "agent_results": [],
        "file_list": ["foo.py"],
        "auth_mode": "direct",
        "api_key": "sk-ant-test",
        "github_token": "ghp_test",
        "model": "claude-sonnet-4-6",
        "max_tokens": 8192,
        "proxy_client_id": "", "proxy_client_secret": "",
        "proxy_url": "", "token_url": "", "scope": "",
        **slices,
    }

    node_fns = [node_pr_agent, node_schema_agent, node_lineage_agent,
                node_arch_drift_agent]
    expected_names = ["pr", "schema", "lineage", "arch_drift"]

    for node_fn, expected_name in zip(node_fns, expected_names):
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({"agent": expected_name, "findings": [], "summary": ""})
        mock_resp.response_metadata = {"usage": {}}
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_resp
        config = {"configurable": {"llm": mock_llm}}

        result = node_fn(base_state, config)

        assert "agent_results" in result
        assert len(result["agent_results"]) == 1
        assert result["agent_results"][0].agent == expected_name


def test_node_agent_handles_failure(sample_agent_input):
    """A node agent that raises must return an error AgentResult, not propagate."""
    from eagleeye.graphs.agent_inputs import slice_all
    from eagleeye.graphs.multi_agent_review import node_schema_agent

    slices = slice_all(sample_agent_input)
    state = {
        "agent_input": sample_agent_input,
        "token_usage": TokenUsage(),
        "agent_results": [],
        "file_list": ["foo.sql"],
        "auth_mode": "direct",
        "api_key": "sk-ant-test",
        "github_token": "ghp_test",
        "model": "claude-sonnet-4-6",
        "max_tokens": 8192,
        "proxy_client_id": "", "proxy_client_secret": "",
        "proxy_url": "", "token_url": "", "scope": "",
        **slices,
    }

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API timeout")
    config = {"configurable": {"llm": mock_llm}}

    result = node_schema_agent(state, config)

    assert len(result["agent_results"]) == 1
    assert result["agent_results"][0].error is not None
    assert "API timeout" in result["agent_results"][0].error


def test_graph_has_five_agent_nodes():
    """The compiled graph must contain all five agent nodes."""
    from eagleeye.graphs.multi_agent_review import _build_graph
    g = _build_graph()
    node_names = set(g.nodes)
    for expected in ("pr_agent", "schema_agent", "lineage_agent", "reference_agent", "arch_drift_agent"):
        assert expected in node_names, f"Missing node: {expected}"


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_agent_finding_valid():
    af = AgentFinding(
        agent="schema",
        file="ddl/tables.sql",
        severity="high",
        category="schema",
        title="Column dropped",
        description="A required column was dropped.",
        fix_suggestion="Add migration guard.",
    )
    assert af.agent == "schema"
    assert af.severity == "high"


def test_agent_result_defaults():
    ar = AgentResult(agent="lineage")
    assert ar.findings == []
    assert ar.summary == ""
    assert ar.error is None


def test_multi_agent_review_input_schema_export():
    schema = MultiAgentReviewInput.model_json_schema()
    assert "diff" in schema["properties"]
    assert "blast_radius_md" in schema["properties"]
    assert "schema_impact_md" in schema["properties"]


# ---------------------------------------------------------------------------
# Context store injection into node_pr_agent and node_reference_agent
# ---------------------------------------------------------------------------

def _base_pr_state(sample_agent_input):
    from eagleeye.graphs.agent_inputs import slice_all
    slices = slice_all(sample_agent_input)
    return {
        "agent_input": sample_agent_input,
        "token_usage": TokenUsage(),
        "agent_results": [],
        "file_list": ["foo.py"],
        "diff": "diff --git a/foo.py",
        "owner": "myorg",
        "repo": "myrepo",
        "auth_mode": "direct",
        "api_key": "sk-ant-test",
        "github_token": "ghp_test",
        "model": "claude-sonnet-4-6",
        "max_tokens": 8192,
        "proxy_client_id": "", "proxy_client_secret": "",
        "proxy_url": "", "token_url": "", "scope": "",
        "context_repos": [],
        **slices,
    }


def test_node_pr_agent_passes_context_and_history_to_llm(sample_agent_input):
    """node_pr_agent includes context_store and pr_history_store content in the LLM call."""
    from eagleeye.graphs.multi_agent_review import node_pr_agent

    state = _base_pr_state(sample_agent_input)

    mock_resp = MagicMock()
    mock_resp.content = json.dumps({"agent": "pr", "findings": [], "summary": ""})
    mock_resp.response_metadata = {"usage": {}}
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_resp
    config = {"configurable": {"llm": mock_llm}}

    with (
        patch(
            "eagleeye.storage.context.get_relevant_contexts",
            return_value=["ctx"],
        ),
        patch(
            "eagleeye.storage.context.format_contexts_as_prompt",
            return_value="## Repo Context\n\narch info",
        ),
        patch(
            "eagleeye.storage.history.get_relevant",
            return_value=["entry"],
        ),
        patch(
            "eagleeye.storage.history.format_history_prompt",
            return_value="## PR History\n\npast change",
        ),
    ):
        node_pr_agent(state, config)

    messages_sent = mock_llm.invoke.call_args[0][0]
    human_content = messages_sent[1].content
    all_text = " ".join(b["text"] for b in human_content if isinstance(b, dict) and "text" in b)
    assert "Repo Context" in all_text
    assert "PR History" in all_text


def test_node_pr_agent_store_failure_still_calls_agent(sample_agent_input):
    """node_pr_agent proceeds normally when context stores raise exceptions."""
    from eagleeye.graphs.multi_agent_review import node_pr_agent

    state = _base_pr_state(sample_agent_input)

    mock_resp = MagicMock()
    mock_resp.content = json.dumps({"agent": "pr", "findings": [], "summary": ""})
    mock_resp.response_metadata = {"usage": {}}
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_resp
    config = {"configurable": {"llm": mock_llm}}

    with (
        patch(
            "eagleeye.storage.context.get_relevant_contexts",
            side_effect=RuntimeError("store unavailable"),
        ),
        patch(
            "eagleeye.storage.history.get_relevant",
            side_effect=RuntimeError("store unavailable"),
        ),
    ):
        result = node_pr_agent(state, config)

    assert result["agent_results"][0].agent == "pr"
    assert mock_llm.invoke.called


def test_node_reference_agent_skips_when_no_matches(sample_agent_input):
    """node_reference_agent returns empty result when reference_matches_md is empty."""
    from eagleeye.graphs.multi_agent_review import node_reference_agent

    ref_state = _base_pr_state(sample_agent_input)
    # reference_agent_input from slice_all has empty reference_matches_md by default
    mock_llm = MagicMock()
    config = {"configurable": {"llm": mock_llm}}

    result = node_reference_agent(ref_state, config)

    assert result["agent_results"][0].agent == "reference"
    assert not mock_llm.invoke.called  # skipped, no matches


def test_node_reference_agent_calls_llm_when_matches_present(sample_agent_input):
    """node_reference_agent calls LLM when reference_matches_md is populated."""
    from dataclasses import replace as _dc_replace
    from eagleeye.graphs.agent_inputs import slice_all
    from eagleeye.graphs.multi_agent_review import node_reference_agent

    slices = slice_all(sample_agent_input)
    ref_inp = slices["reference_agent_input"]
    ref_inp_with_matches = _dc_replace(
        ref_inp,
        reference_matches_md="## Reference matches in `myorg/ref-repo`\n\n- `my_func`",
    )

    ref_state = _base_pr_state(sample_agent_input)
    ref_state["reference_agent_input"] = ref_inp_with_matches

    mock_resp = MagicMock()
    mock_resp.content = json.dumps({"agent": "reference", "findings": [], "summary": ""})
    mock_resp.response_metadata = {"usage": {}}
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_resp
    config = {"configurable": {"llm": mock_llm}}

    result = node_reference_agent(ref_state, config)

    assert result["agent_results"][0].agent == "reference"
    assert mock_llm.invoke.called
