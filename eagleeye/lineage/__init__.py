"""Optional database lineage facade.

Regex-based Snowflake usage extraction works without extra deps.
Snapshot enrichment and live Snowflake refresh require ``pip install 'eagleeye[lineage]'``.
"""

from __future__ import annotations

from typing import Any

from ._availability import INSTALL_HINT, is_available, missing_dependencies, require_lineage
from .api import (
    enrich_extract_from_snapshot,
    extract_snowflake_usages,
    format_as_markdown,
    get_connection,
    infer_pr_lineage,
    make_db_resolver,
    refresh_metadata,
    resolve_lineage,
)

__all__ = [
    "INSTALL_HINT",
    "LineageInfo",
    "SnowflakeObjectUsage",
    "SnowflakeUsageExtract",
    "enrich_extract_from_snapshot",
    "extract_snowflake_usages",
    "format_as_markdown",
    "get_connection",
    "infer_pr_lineage",
    "is_available",
    "make_db_resolver",
    "missing_dependencies",
    "refresh_metadata",
    "require_lineage",
    "resolve_lineage",
]


def __getattr__(name: str) -> Any:
    if name in ("LineageInfo", "SnowflakeObjectUsage", "SnowflakeUsageExtract"):
        from eagleeye.db_lineage import extractor as _ext

        return getattr(_ext, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
