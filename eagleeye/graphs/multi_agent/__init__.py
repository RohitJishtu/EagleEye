"""LangGraph multi-agent PR review workflow.

Five specialized agents run as parallel LangGraph branches, each analysing one domain:
  - pr_agent        : code logic, correctness, performance, security
  - schema_agent    : DDL lineage, type mismatches, migration safety
  - lineage_agent   : pipeline dependencies, fail_on_run_failure, alerts
  - reference_agent : cross-repo dependency impact (symbol + schema consumers in reference repo)
  - arch_drift_agent: layer violations, cross-layer imports

LangGraph fans out from prepare_agent_input to all five nodes concurrently, waits for
all branches, then fans in to synthesize_findings via Annotated list reducers.
"""

from __future__ import annotations

from .graph import _build_graph, run_multi_agent_pr_review_graph
from .keywords import (
    _ARCH_KEYWORDS,
    _FEATURE_KEYWORDS,
    _PIPELINE_KEYWORDS,
    _SCHEMA_KEYWORDS,
    _has_relevant_files,
)
from .nodes import (
    node_arch_drift_agent,
    node_lineage_agent,
    node_pr_agent,
    node_reference_agent,
    node_schema_agent,
    synthesize_findings,
)
from .prepare import prepare_agent_input
from .runners import _parse_agent_response
from .state import MultiAgentReviewState

__all__ = [
    "MultiAgentReviewState",
    "_ARCH_KEYWORDS",
    "_FEATURE_KEYWORDS",
    "_PIPELINE_KEYWORDS",
    "_SCHEMA_KEYWORDS",
    "_build_graph",
    "_has_relevant_files",
    "_parse_agent_response",
    "node_arch_drift_agent",
    "node_lineage_agent",
    "node_pr_agent",
    "node_reference_agent",
    "node_schema_agent",
    "prepare_agent_input",
    "run_multi_agent_pr_review_graph",
    "synthesize_findings",
]
