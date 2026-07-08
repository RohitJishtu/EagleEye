"""Compatibility shim — multi-agent graph split across ``eagleeye.graphs.multi_agent``."""

from eagleeye.graphs.multi_agent.graph import _build_graph
from eagleeye.graphs.multi_agent.nodes import (
    node_arch_drift_agent,
    node_lineage_agent,
    node_pr_agent,
    node_reference_agent,
    node_schema_agent,
    synthesize_findings,
)
from eagleeye.graphs.multi_agent.runners import _parse_agent_response

__all__ = [
    "_build_graph",
    "_parse_agent_response",
    "node_arch_drift_agent",
    "node_lineage_agent",
    "node_pr_agent",
    "node_reference_agent",
    "node_schema_agent",
    "synthesize_findings",
]
