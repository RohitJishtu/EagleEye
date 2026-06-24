"""Public lineage API — regex extraction always works; enrichment needs [lineage] extra."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._availability import is_available, require_lineage, require_lineage_refresh

if TYPE_CHECKING:
    from eagleeye.db_lineage.extractor import (
        LineageInfo,
        SnowflakeObjectUsage,
        SnowflakeUsageExtract,
    )


def extract_snowflake_usages(diff: str, files: dict[str, str]) -> "SnowflakeUsageExtract":
    from eagleeye.db_lineage.extractor import extract_snowflake_usages as _fn

    return _fn(diff, files)


def infer_pr_lineage(usages: list["SnowflakeObjectUsage"]) -> None:
    from eagleeye.db_lineage.extractor import _infer_pr_lineage

    _infer_pr_lineage(usages)


def format_as_markdown(extract: "SnowflakeUsageExtract") -> str:
    from eagleeye.db_lineage.extractor import format_as_markdown as _fn

    return _fn(extract)


def resolve_lineage(extract: "SnowflakeUsageExtract", resolver_fn: Any) -> "SnowflakeUsageExtract":
    from eagleeye.db_lineage.extractor import resolve_lineage as _fn

    return _fn(extract, resolver_fn)


def make_db_resolver(**kwargs: Any) -> Any:
    require_lineage(feature="DB lineage resolver")
    from eagleeye.db_lineage.snowflake_metadata import make_db_resolver as _fn

    return _fn(**kwargs)


def enrich_extract_from_snapshot(
    extract: "SnowflakeUsageExtract",
    snapshot_path: str | Path | None,
) -> "SnowflakeUsageExtract":
    """Enrich usages with upstream/downstream from a local JSON snapshot when available."""
    if not snapshot_path or not is_available():
        return extract
    path = Path(snapshot_path).expanduser()
    if not path.exists():
        return extract
    try:
        return resolve_lineage(extract, make_db_resolver(json_path=str(path)))
    except Exception:
        return extract


def get_connection(**kwargs: Any) -> Any:
    require_lineage_refresh(feature="Snowflake connection")
    from eagleeye.db_lineage.snowflake_metadata import get_connection as _fn

    return _fn(**kwargs)


def refresh_metadata(conn: Any, **kwargs: Any) -> dict[str, str]:
    require_lineage_refresh(feature="lineage snapshot refresh")
    from eagleeye.db_lineage.snowflake_metadata import refresh_metadata as _fn

    return _fn(conn, **kwargs)
