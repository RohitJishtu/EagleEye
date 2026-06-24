"""Typed state for the multi-agent PR review LangGraph."""

from __future__ import annotations

import operator
from collections import deque
from typing import Annotated, Any, Optional, TypedDict

from ...integrations.anthropic.client import TokenUsage
from ...core.models import (
    AgentResult,
    MultiAgentReviewInput,
    PRReviewResult,
)
from ..agent_inputs import (
    ArchDriftInput,
    LineageAgentInput,
    PrAgentInput,
    ReferenceAgentInput,
    SchemaAgentInput,
    SynthesisInput,
)


class MultiAgentReviewState(TypedDict):
    # Inputs
    owner: str
    repo: str
    pr_number: int
    post_comment: bool
    api_key: str
    github_token: str
    github_tokens: dict
    model: str
    max_tokens: int
    auth_mode: str
    proxy_client_id: str
    proxy_client_secret: str
    proxy_url: str
    token_url: str
    scope: str
    max_files: int
    max_file_bytes: int
    max_total_bytes: int
    # Fetched
    diff: str
    pr_metadata: dict
    file_list: list[str]
    full_file_contents: dict[str, str]
    base_file_contents: dict[str, str]
    structural_diff: Optional[Any]  # StructuralSymbolDiff at runtime
    files_fetched: int
    files_total: int
    file_manifest: list
    # Internal state (rate limiting)
    search_window: deque[float]
    # Prepared
    agent_input: Optional[MultiAgentReviewInput]
    # Per-agent typed input slices (populated by prepare_agent_input)
    pr_agent_input:       Optional[PrAgentInput]
    schema_agent_input:   Optional[SchemaAgentInput]
    lineage_agent_input:  Optional[LineageAgentInput]
    reference_agent_input: Optional[ReferenceAgentInput]
    reference_repos: list[str]
    arch_drift_input:     Optional[ArchDriftInput]
    synthesis_input:      Optional[SynthesisInput]
    # Parallel fan-in: each branch appends one item; LangGraph concatenates via operator.add
    agent_results: Annotated[list[AgentResult], operator.add]
    raw_usage: Annotated[list[dict], operator.add]
    # Output
    result: Optional[PRReviewResult]
    schema_impact: Optional[Any]
    context_repos: Optional[list[str]]
    token_usage: TokenUsage
    error: Optional[str]
