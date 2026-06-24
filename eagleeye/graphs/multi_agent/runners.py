"""LLM call helpers for each specialist agent and synthesis."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

from ...integrations.anthropic.client import (
    _AGENT_RESULT_SCHEMA,
    _PR_REVIEW_SCHEMA,
    _clean_json,
)
from ...core.models import AgentFinding, AgentResult, PRReviewResult
from ...core.prompt_loader import get_prompt
from ..agent_inputs import (
    ArchDriftInput,
    LineageAgentInput,
    PrAgentInput,
    ReferenceAgentInput,
    SchemaAgentInput,
    SynthesisInput,
)
from .._shared import (
    make_cached_system_message,
    make_content_block,
)

if TYPE_CHECKING:
    pass

_AGENT_LABEL = {
    "pr": "🔍 pr",
    "schema": "🗄️  schema",
    "lineage": "🔗 lineage",
    "reference": "📎 reference",
    "arch_drift": "🏗️  arch_drift",
}


def _parse_agent_response(raw: str, agent_name: str) -> AgentResult:
    try:
        data = json.loads(_clean_json(raw))
        if isinstance(data, list):
            findings = [AgentFinding(agent=agent_name, **f) for f in data]
            return AgentResult(agent=agent_name, findings=findings)
        if isinstance(data, dict):
            findings_raw = data.get("findings", [])
            findings = [
                AgentFinding(
                    agent=agent_name,
                    **{k: v for k, v in f.items() if k != "agent"},
                )
                for f in findings_raw
            ]
            return AgentResult(
                agent=agent_name,
                findings=findings,
                summary=data.get("summary", ""),
            )
    except Exception as exc:
        return AgentResult(agent=agent_name, error=f"Parse error: {exc}")
    return AgentResult(agent=agent_name)


def _agent_log(name: str, msg: str) -> None:
    from ...presentation.terminal import display_info
    label = _AGENT_LABEL.get(name, name)
    display_info(f"{label}  {msg}")


def _findings_summary(result: AgentResult) -> str:
    if result.error:
        return f"FAILED — {result.error}"
    n = len(result.findings)
    if n == 0:
        return "no findings"
    by_sev: dict[str, int] = {}
    for f in result.findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    parts = [f"{v} {k}" for k, v in sorted(by_sev.items(), key=lambda x: ["critical","high","medium","low","info"].index(x[0]) if x[0] in ["critical","high","medium","low","info"] else 9)]
    return f"{n} finding{'s' if n != 1 else ''} ({', '.join(parts)})"


def _run_agent(name: str, prompt_key: str, llm, user_blocks: list) -> tuple[AgentResult, dict]:
    _agent_log(name, "starting…")
    system = make_cached_system_message(get_prompt(prompt_key))
    user_blocks = user_blocks + [
        make_content_block(f"Respond with a JSON object exactly matching this schema:\n{_AGENT_RESULT_SCHEMA}")
    ]
    response = llm.invoke([system, HumanMessage(content=user_blocks)])
    raw = response.content if isinstance(response.content, str) else str(response.content)
    result = _parse_agent_response(raw, name)
    _agent_log(name, f"done — {_findings_summary(result)}")
    return result, response.response_metadata


def _call_pr_agent(
    inp: PrAgentInput,
    llm,
    *,
    context_md: str = "",
    history_md: str = "",
) -> tuple[AgentResult, dict]:
    header = (
        f"PR Title: {inp.pr_metadata.get('title', '')}\n"
        f"PR Author: {inp.pr_metadata.get('author', '')}\n"
        f"Base Branch: {inp.pr_metadata.get('base', '')}\n"
        f"Description: {inp.pr_metadata.get('body', 'No description provided')}\n"
        f"Files Changed ({len(inp.file_list)}): {', '.join(inp.file_list)}\n\n"
        f"## Diff\n\n{inp.diff}"
    )
    user_blocks = [make_content_block(header, cache=len(inp.diff.encode()) > 10_000)]

    if context_md:
        user_blocks.append(make_content_block(context_md, cache=True))

    if inp.full_file_contents:
        files_text = "\n\n".join(
            f"### {path}\n```\n{content[:inp.max_file_bytes]}\n```"
            for path, content in inp.full_file_contents.items()
        )
        user_blocks.append(make_content_block(
            f"## Full File Contents\n\n{files_text}",
            cache=len(files_text.encode()) > 10_000,
        ))

    if history_md:
        user_blocks.append(make_content_block(history_md, cache=False))

    if inp.blast_radius_md:
        user_blocks.append(make_content_block(
            f"## Blast Radius — Cross-file Symbol Impact\n\n{inp.blast_radius_md}",
            cache=len(inp.blast_radius_md.encode()) > 5_000,
        ))

    user_blocks.extend([
        make_content_block(f"## Test Coverage Analysis\n\n{inp.test_coverage_md}"),
        make_content_block(f"## Security Scan Results\n\n{inp.security_scan_md}"),
    ])
    return _run_agent("pr", "agents.pr", llm, user_blocks)


def _call_schema_agent(inp: SchemaAgentInput, llm) -> tuple[AgentResult, dict]:
    user_blocks = [
        make_content_block(f"## Schema Impact Analysis (pre-computed)\n\n{inp.schema_impact_md}", cache=True),
        make_content_block(
            f"## Schema-Relevant Diff Sections\n\n{inp.schema_diff}",
            cache=len(inp.schema_diff.encode()) > 10_000,
        ),
        make_content_block(f"Files Changed: {', '.join(inp.file_list)}"),
    ]
    return _run_agent("schema", "agents.schema", llm, user_blocks)


def _call_lineage_agent(inp: LineageAgentInput, llm) -> tuple[AgentResult, dict]:
    user_blocks: list = []
    if inp.snowflake_lineage_md:
        user_blocks.append(make_content_block(inp.snowflake_lineage_md, cache=True))

    if inp.pipeline_file_contents:
        files_text = "\n\n".join(
            f"### {path}\n```yaml\n{content[:inp.max_file_bytes]}\n```"
            for path, content in inp.pipeline_file_contents.items()
        )
        user_blocks.append(make_content_block(
            f"## Pipeline File Contents\n\n{files_text}",
            cache=len(files_text.encode()) > 10_000,
        ))

    user_blocks.extend([
        make_content_block(
            f"## Pipeline / CI-CD Diff Sections\n\n{inp.pipeline_diff}",
            cache=len(inp.pipeline_diff.encode()) > 10_000,
        ),
        make_content_block(f"Files Changed: {', '.join(inp.file_list)}"),
    ])
    return _run_agent("lineage", "agents.lineage", llm, user_blocks)


def _call_reference_agent(inp: ReferenceAgentInput, llm) -> tuple[AgentResult, dict]:
    user_blocks = [
        make_content_block(inp.reference_matches_md, cache=True),
        make_content_block(
            f"## PR Diff (for context)\n\nFiles changed: {', '.join(inp.file_list)}\n\n{inp.diff[:8_000]}",
            cache=False,
        ),
    ]
    return _run_agent("reference", "agents.reference", llm, user_blocks)


def _call_arch_drift_agent(inp: ArchDriftInput, llm) -> tuple[AgentResult, dict]:
    user_blocks = [make_content_block(
        f"## Files Changed\n{', '.join(inp.file_list)}\n\n"
        f"## Added Import Statements\n```\n{inp.added_imports}\n```"
    )]
    return _run_agent("arch_drift", "agents.arch_drift", llm, user_blocks)


def _call_synthesis_agent(
    inp: SynthesisInput,
    llm,
) -> tuple[PRReviewResult, dict]:
    from pydantic import ValidationError

    system = make_cached_system_message(get_prompt("synthesis"))

    all_findings: list[dict] = []
    agent_summaries: list[str] = []
    for ar in inp.agent_results:
        if ar.error:
            agent_summaries.append(f"- {ar.agent}: FAILED — {ar.error}")
            continue
        agent_summaries.append(
            f"- {ar.agent}: {len(ar.findings)} findings — {ar.summary or 'no summary'}"
        )
        all_findings.extend(f.model_dump() for f in ar.findings)

    findings_json = json.dumps(all_findings, indent=2)
    metadata = inp.pr_metadata
    pr_context = (
        f"PR Title: {metadata.get('title', '')}\n"
        f"Author: {metadata.get('author', '')}\n"
        f"Files Changed ({len(inp.file_list)}): {', '.join(inp.file_list)}\n"
    )

    user_blocks = [
        make_content_block(
            f"## PR Context\n{pr_context}\n\n"
            f"## Agent Summaries\n" + "\n".join(agent_summaries) + "\n\n"
            f"## All Agent Findings\n```json\n{findings_json}\n```",
            cache=len(findings_json.encode()) > 10_000,
        ),
        *(
            [make_content_block(
                f"## EDP Impact (pre-computed)\n\n{inp.snowflake_lineage_md}",
                cache=True,
            )]
            if inp.snowflake_lineage_md else []
        ),
        make_content_block(
            f"Synthesize the above into a final PR review. "
            f"Respond with valid JSON exactly matching this schema:\n{_PR_REVIEW_SCHEMA}"
        ),
    ]

    response = llm.invoke([system, HumanMessage(content=user_blocks)])
    raw = response.content if isinstance(response.content, str) else str(response.content)
    try:
        result = PRReviewResult.model_validate_json(_clean_json(raw))
    except (ValueError, ValidationError) as exc:
        raise RuntimeError(
            f"Synthesis agent returned unexpected response: {raw[:200]!r}"
        ) from exc
    return result, response.response_metadata
