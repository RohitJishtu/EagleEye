"""LangGraph node functions for specialist agents and synthesis."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from eagleeye.storage import context as context_store
from eagleeye.storage import history as pr_history_store
from ...integrations.anthropic.client import TokenUsage
from ...core.models import AgentResult
from ..agent_inputs import SynthesisInput
from .keywords import (
    _ARCH_KEYWORDS,
    _PIPELINE_KEYWORDS,
    _SCHEMA_KEYWORDS,
    _has_relevant_files,
)
from .runners import (
    _call_arch_drift_agent,
    _call_lineage_agent,
    _call_pr_agent,
    _call_reference_agent,
    _call_schema_agent,
    _call_synthesis_agent,
)
from .state import MultiAgentReviewState


def node_pr_agent(state: MultiAgentReviewState, config: RunnableConfig) -> dict:
    context_md = ""
    try:
        relevant = context_store.get_relevant_contexts(
            file_list=state["file_list"],
            diff=state.get("diff", ""),
            extra_repos=state.get("context_repos"),
        )
        context_md = context_store.format_contexts_as_prompt(relevant)
    except Exception:
        pass

    history_md = ""
    try:
        entries = pr_history_store.get_relevant(state["owner"], state["repo"], state["file_list"])
        if entries:
            history_md = pr_history_store.format_history_prompt(entries)
    except Exception:
        pass

    llm = config["configurable"]["llm"]
    try:
        result, metadata = _call_pr_agent(
            state["pr_agent_input"], llm,
            context_md=context_md,
            history_md=history_md,
        )
    except Exception as exc:
        result, metadata = AgentResult(agent="pr", error=str(exc)), {}
    return {"agent_results": [result], "raw_usage": [metadata]}


def node_schema_agent(state: MultiAgentReviewState, config: RunnableConfig) -> dict:
    from ...presentation.terminal import display_phase_skipped
    if not _has_relevant_files(state["file_list"], _SCHEMA_KEYWORDS):
        display_phase_skipped(
            "Phase 5 · Schema agent",
            "No SQL/DDL/ORM/migration files in this PR — schema review not applicable",
            "graphs/multi_agent/nodes.py → node_schema_agent",
        )
        return {"agent_results": [AgentResult(agent="schema")], "raw_usage": [{}]}
    llm = config["configurable"]["llm"]
    try:
        result, metadata = _call_schema_agent(state["schema_agent_input"], llm)
    except Exception as exc:
        result, metadata = AgentResult(agent="schema", error=str(exc)), {}
    return {"agent_results": [result], "raw_usage": [metadata]}


def node_lineage_agent(state: MultiAgentReviewState, config: RunnableConfig) -> dict:
    from ...presentation.terminal import display_phase_skipped
    if not _has_relevant_files(state["file_list"], _PIPELINE_KEYWORDS):
        display_phase_skipped(
            "Phase 5 · Lineage agent",
            "No pipeline/DAG/YAML/workflow files in this PR — lineage review not applicable",
            "graphs/multi_agent/nodes.py → node_lineage_agent",
        )
        return {"agent_results": [AgentResult(agent="lineage")], "raw_usage": [{}]}
    llm = config["configurable"]["llm"]
    try:
        result, metadata = _call_lineage_agent(state["lineage_agent_input"], llm)
    except Exception as exc:
        result, metadata = AgentResult(agent="lineage", error=str(exc)), {}
    return {"agent_results": [result], "raw_usage": [metadata]}


def node_reference_agent(state: MultiAgentReviewState, config: RunnableConfig) -> dict:
    from ...presentation.terminal import display_phase_skipped

    inp = state.get("reference_agent_input")
    if not inp or not inp.reference_matches_md:
        display_phase_skipped(
            "Phase 5 · Reference agent",
            "No reference index or no matches found — cross-repo dependency review not applicable",
            "graphs/multi_agent/nodes.py → node_reference_agent",
        )
        return {"agent_results": [AgentResult(agent="reference")], "raw_usage": [{}]}

    llm = config["configurable"]["llm"]
    try:
        result, metadata = _call_reference_agent(inp, llm)
    except Exception as exc:
        result, metadata = AgentResult(agent="reference", error=str(exc)), {}
    return {"agent_results": [result], "raw_usage": [metadata]}


def node_arch_drift_agent(state: MultiAgentReviewState, config: RunnableConfig) -> dict:
    from ...presentation.terminal import display_phase_skipped
    if not _has_relevant_files(state["file_list"], _ARCH_KEYWORDS):
        display_phase_skipped(
            "Phase 5 · Arch drift agent",
            "No Python/JS/TS source files in this PR — architectural layer review not applicable",
            "graphs/multi_agent/nodes.py → node_arch_drift_agent",
        )
        return {"agent_results": [AgentResult(agent="arch_drift")], "raw_usage": [{}]}
    llm = config["configurable"]["llm"]
    try:
        result, metadata = _call_arch_drift_agent(state["arch_drift_input"], llm)
    except Exception as exc:
        result, metadata = AgentResult(agent="arch_drift", error=str(exc)), {}
    return {"agent_results": [result], "raw_usage": [metadata]}


def synthesize_findings(state: MultiAgentReviewState, config: RunnableConfig) -> dict:
    from ...presentation.terminal import display_info, display_phase
    from .._shared import accumulate_usage

    total = sum(len(ar.findings) for ar in state["agent_results"] if not ar.error)
    display_phase(
        "Phase 6 · Synthesizing findings into final verdict",
        "graphs/multi_agent/nodes.py → synthesize_findings",
    )
    display_info(f"Synthesizing {total} total findings into final verdict…")
    llm = config["configurable"]["llm"]

    agent_inp = state.get("agent_input")
    synth_inp = SynthesisInput(
        agent_results=state["agent_results"],
        pr_metadata=state["pr_metadata"],
        file_list=state["file_list"],
        snowflake_lineage_md=agent_inp.snowflake_lineage_md if agent_inp else "",
    )

    usage = TokenUsage()
    for meta in state.get("raw_usage", []):
        accumulate_usage(usage, meta)

    result, metadata = _call_synthesis_agent(synth_inp, llm)
    accumulate_usage(usage, metadata)

    from ...workflows.review.verdict import enforce_verdict_rules, group_similar_findings
    result = enforce_verdict_rules(result)
    result = result.model_copy(
        update={"file_comments": group_similar_findings(result.file_comments)}
    )

    n_findings = sum(len(ar.findings) for ar in state["agent_results"] if ar.findings)
    n_high = sum(
        1 for ar in state["agent_results"] if ar.findings
        for f in ar.findings if getattr(f, "severity", "") == "HIGH"
    )
    verdict_label = {
        "approve": "Approved",
        "request_changes": "Needs Changes",
        "comment": "Needs Attention",
    }.get(result.overall_verdict, result.overall_verdict)
    summary = (
        f"{n_findings} finding{'s' if n_findings != 1 else ''} across 5 agents. "
        f"Verdict: {verdict_label}."
        + (f" {n_high} HIGH item{'s' if n_high != 1 else ''} require action before merge." if n_high else "")
    )

    return {"result": result, "token_usage": usage}
