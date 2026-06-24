"""Typed input slices for each specialist agent in the multi-agent review graph.

MultiAgentReviewInput is the full assembly bundle. slice_all() derives five
focused views from it. SynthesisInput is built separately in synthesize_findings
(requires agent_results which are only available after the fan-out completes).
"""
from __future__ import annotations

from dataclasses import dataclass


_SCHEMA_KEYWORDS = (
    # SQL / DDL files
    ".sql", ".ddl", ".hql",
    # Python migration frameworks
    "migration", "alembic",
    # ORM / model files (standard naming)
    "schema", "model.py", "models.py",
    # Pydantic, serializers, DTOs, TypedDict
    "pydantic", "serializer", "dto", "typedef",
    # Common type/table definition filenames
    "types.py", "table.py", "tables.py", "entities.py",
)
_PIPELINE_KEYWORDS = (".yml", ".yaml", "dag", "airflow", "dbt", "pipeline", "workflow", "spark", "databricks")


def _filter_diff_by_keywords(diff: str, keywords: tuple[str, ...]) -> str:
    lines = diff.splitlines(keepends=True)
    blocks: list[str] = []
    current: list[str] = []
    in_target = False
    for line in lines:
        if line.startswith("diff --git "):
            if in_target and current:
                blocks.extend(current)
            current = [line]
            in_target = any(kw in line.lower() for kw in keywords)
        else:
            current.append(line)
    if in_target and current:
        blocks.extend(current)
    return "".join(blocks) or "(no relevant diff sections)"


def _added_import_lines(diff: str) -> str:
    """Extract import lines that are added (+) or present as context in the diff."""
    result = []
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        # Added lines: strip the leading '+'
        if line.startswith("+"):
            stripped = line[1:].strip()
            if stripped.startswith(("import ", "from ")):
                result.append(stripped)
        # Context lines in unified diffs (no prefix or space prefix)
        elif line.startswith(" ") or (not line.startswith("-") and not line.startswith("diff ") and not line.startswith("index ") and not line.startswith("@@")):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                result.append(stripped)
    return "\n".join(result) if result else "(no import changes)"


@dataclass
class PrAgentInput:
    diff: str
    pr_metadata: dict
    file_list: list[str]
    full_file_contents: dict[str, str]
    blast_radius_md: str
    test_coverage_md: str
    security_scan_md: str
    max_file_bytes: int


@dataclass
class SchemaAgentInput:
    schema_diff: str        # pre-filtered to _SCHEMA_KEYWORDS
    schema_impact_md: str
    file_list: list[str]


@dataclass
class LineageAgentInput:
    snowflake_lineage_md: str
    pipeline_file_contents: dict[str, str]  # pre-filtered to pipeline keywords
    pipeline_diff: str                       # pre-filtered to _PIPELINE_KEYWORDS
    file_list: list[str]
    max_file_bytes: int


@dataclass
class ReferenceAgentInput:
    reference_matches_md: str   # pre-computed from reference_store.search_indexes
    diff: str                   # full PR diff for context
    file_list: list[str]        # changed files in this PR


@dataclass
class ArchDriftInput:
    file_list: list[str]
    added_imports: str       # pre-extracted via _added_import_lines(diff)


@dataclass
class SynthesisInput:
    agent_results: list      # list[AgentResult]
    pr_metadata: dict
    file_list: list[str]
    snowflake_lineage_md: str


def slice_all(inp) -> dict:
    """Derive 5 typed agent input slices from a MultiAgentReviewInput bundle.

    Returns a dict keyed by MultiAgentReviewState field names.
    SynthesisInput is not included — it requires agent_results from the fan-out.
    ReferenceAgentInput.reference_matches_md is empty here; populated in prepare_agent_input.
    """
    diff = inp.diff
    files = inp.full_file_contents

    pipeline_files = {
        path: content for path, content in files.items()
        if any(kw in path.lower() for kw in (".yml", ".yaml", "dag", "pipeline", "workflow"))
    }

    return {
        "pr_agent_input": PrAgentInput(
            diff=diff,
            pr_metadata=inp.pr_metadata,
            file_list=inp.file_list,
            full_file_contents=files,
            blast_radius_md=inp.blast_radius_md,
            test_coverage_md=inp.test_coverage_md,
            security_scan_md=inp.security_scan_md,
            max_file_bytes=inp.max_file_bytes,
        ),
        "schema_agent_input": SchemaAgentInput(
            schema_diff=_filter_diff_by_keywords(diff, _SCHEMA_KEYWORDS),
            schema_impact_md=inp.schema_impact_md,
            file_list=inp.file_list,
        ),
        "lineage_agent_input": LineageAgentInput(
            snowflake_lineage_md=inp.snowflake_lineage_md,
            pipeline_file_contents=pipeline_files,
            pipeline_diff=_filter_diff_by_keywords(diff, _PIPELINE_KEYWORDS),
            file_list=inp.file_list,
            max_file_bytes=inp.max_file_bytes,
        ),
        "reference_agent_input": ReferenceAgentInput(
            reference_matches_md="",   # populated in prepare_agent_input after search_indexes
            diff=inp.diff,
            file_list=inp.file_list,
        ),
        "arch_drift_input": ArchDriftInput(
            file_list=inp.file_list,
            added_imports=_added_import_lines(diff),
        ),
    }
