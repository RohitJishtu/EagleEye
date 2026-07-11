"""Build a lightweight RepoMap without a full LLM repo read."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from ..core.config import EagleEyeConfig, resolve_github_token
from ..core.models import RepoMap
from ..integrations.github import GitHubClient
from ..storage.reference import load_index
from ..workflows.repo_read.helpers import _build_tree_string, _select_key_files

_README_MAX_CHARS = 2_000
_TREE_MAX_ENTRIES = 120

# Path/name hints → signal labels
_SIGNAL_RULES: list[tuple[str, str]] = [
    ("dbt_project.yml", "dbt"),
    ("dagster.yaml", "dagster"),
    ("prefect.yaml", "prefect"),
    ("airflow", "airflow"),
    ("dags/", "airflow"),
    (".github/workflows/", "github-actions"),
    ("Dockerfile", "docker"),
    ("docker-compose", "docker"),
    ("pyproject.toml", "python-packaging"),
    ("package.json", "nodejs"),
    ("go.mod", "go"),
    ("snowflake", "snowflake"),
    ("spark", "spark"),
    ("kafka", "kafka"),
    ("models/", "data-models"),
    ("cicd/", "cicd"),
    ("terraform", "terraform"),
    ("kubernetes", "kubernetes"),
]


def _extension_counts(paths: list[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in paths:
        if "." in path.rsplit("/", 1)[-1]:
            ext = "." + path.rsplit(".", 1)[-1].lower()
            counts[ext] += 1
    return dict(counts.most_common(15))


def _top_level_dirs(paths: list[str]) -> list[str]:
    dirs: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if len(parts) > 1:
            dirs.add(parts[0])
    return sorted(dirs)[:20]


def _detect_signals(paths: list[str]) -> list[str]:
    joined = "\n".join(paths).lower()
    found: list[str] = []
    for pattern, label in _SIGNAL_RULES:
        if pattern.lower() in joined and label not in found:
            found.append(label)
    return found


def build_repo_map_from_parts(
    owner: str,
    repo: str,
    branch: str,
    meta: dict,
    tree: list[dict],
    readme: str,
) -> RepoMap:
    """Build RepoMap from already-fetched GitHub data (no extra API calls)."""
    blob_paths = [item["path"] for item in tree if item.get("type") == "blob"]
    key_files = _select_key_files(blob_paths)
    signals = _detect_signals(blob_paths + key_files)
    ref_index = load_index(owner, repo)
    ref_symbols = len(ref_index.index) if ref_index else 0

    return RepoMap(
        owner=owner,
        repo=repo,
        branch=branch,
        built_at=datetime.now(timezone.utc).isoformat(),
        html_url=meta.get("html_url", ""),
        description=meta.get("description", ""),
        primary_language=meta.get("language", ""),
        topics=meta.get("topics", []),
        file_count=len(blob_paths),
        top_level_dirs=_top_level_dirs(blob_paths),
        languages=_extension_counts(blob_paths),
        key_files=key_files,
        readme_excerpt=readme[:_README_MAX_CHARS].strip(),
        file_tree_excerpt=_build_tree_string(tree, max_entries=_TREE_MAX_ENTRIES),
        signals=signals,
        reference_index_built=ref_index is not None,
        reference_symbol_count=ref_symbols,
    )


def build_repo_map(
    owner: str,
    repo: str,
    config: EagleEyeConfig,
    branch: Optional[str] = None,
) -> RepoMap:
    """Fetch repo metadata and tree, produce a deterministic RepoMap."""
    token = resolve_github_token(owner, config)
    github = GitHubClient(token)

    try:
        meta = github.get_repo_metadata(owner, repo)
        effective_branch = branch or meta.get("default_branch", "main")
        tree = github.get_repo_tree(owner, repo, effective_branch)
        readme = github.get_repo_readme(owner, repo)
    finally:
        github.close()

    return build_repo_map_from_parts(
        owner, repo, effective_branch, meta, tree, readme,
    )
