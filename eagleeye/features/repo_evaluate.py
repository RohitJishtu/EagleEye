"""Repo evaluation feature — one-command repo assessment."""

from __future__ import annotations

from typing import Optional

from ..integrations.anthropic.client import TokenUsage
from ..core.config import EagleEyeConfig
from ..core.models import RepoEvaluationResult


def run_repo_evaluate(
    owner: str,
    repo: str,
    config: EagleEyeConfig,
    branch: Optional[str] = None,
    scoped_path: Optional[str] = None,
    no_llm: bool = False,
    include_data_dirs: bool = False,
) -> tuple[RepoEvaluationResult, TokenUsage, str]:
    from ..graphs.repo_evaluate.graph import run_repo_evaluate_graph

    return run_repo_evaluate_graph(
        owner,
        repo,
        config,
        branch=branch,
        scoped_path=scoped_path,
        no_llm=no_llm,
        include_data_dirs=include_data_dirs,
    )
