"""Database-agnostic lineage logic.

Generic BFS traversal, resolver factories, and result structures that work
with any database (Snowflake, PostgreSQL, BigQuery, etc.).

Depends on:
  - eagleeye.db_lineage.provider (base classes)
  - pandas (for DataFrame operations)
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

from .provider import DBLineageProvider, LineageResult

if TYPE_CHECKING:
    pass


_SAFE_OBJ_RE = _re.compile(r"^[A-Z0-9_.]+$")


def _validate_obj_name(name: str) -> str:
    """Uppercase and validate an object name.

    Raises ValueError if the name contains characters outside [A-Z0-9_.].
    This prevents SQL injection when names are interpolated into IN-clauses.
    """
    n = name.upper()
    if not _SAFE_OBJ_RE.match(n):
        raise ValueError(f"Unsafe object name rejected: {name!r}")
    return n


@dataclass
class LineageInfo:
    """Lineage result for a single Snowflake object.

    upstream   : where data comes FROM (job name, repo, table, etc.)
    downstream : where data goes TO
    note       : any extra context to surface in the report
    """
    upstream: list[str] = field(default_factory=list)
    downstream: list[str] = field(default_factory=list)
    note: str = ""


def _build_bfs_indices(df):
    """Build GroupBy indices for fast BFS lookups.

    Returns:
        (up_idx, down_idx): GroupBy objects keyed by uppercased OBJ and
        REFERENCED_OBJECT_NAME respectively.
    """
    up_col = df["OBJ"].str.upper()
    down_col = df["REFERENCED_OBJECT_NAME"].str.upper()
    up_idx = df.groupby(up_col)
    down_idx = df.groupby(down_col)
    return up_idx, down_idx


def _bfs(df, start: str, mode: str, depth: int) -> list:
    """BFS over the dependency graph using GroupBy index.

    Fix 1: Build a GroupBy index once and call .get_group() — O(1) per lookup
    instead of O(N) per lookup — avoiding a full-DataFrame scan per frontier node.
    Group rows are converted to dicts via DataFrame.to_dict('records') on the
    small per-node group.

    mode='upstream'   — objects that `start` references (its dependencies)
    mode='downstream' — objects that reference `start` (its dependents)
    """
    up_idx, down_idx = _build_bfs_indices(df)

    visited = {start}
    frontier = {start}
    rows = []

    for hop in range(1, depth + 1):
        if not frontier:
            break
        next_frontier: set[str] = set()

        for obj in frontier:
            if mode == "upstream":
                idx = up_idx
                name_col, schema_col, db_col = (
                    "REFERENCED_OBJECT_NAME",
                    "REFERENCED_SCHEMA",
                    "REFERENCED_DATABASE",
                )
            else:
                idx = down_idx
                name_col, schema_col, db_col = "OBJ", "SCHEMA", "DB"

            group = idx.get_group(obj) if obj in idx.groups else None
            if group is None:
                continue

            # Convert the small per-node group to records and iterate.
            for row in group.to_dict("records"):
                neighbour = str(row[name_col]).upper()
                if neighbour in visited:
                    continue
                visited.add(neighbour)
                next_frontier.add(neighbour)
                row_out = {
                    "Hop": hop,
                    "ObjectName": neighbour,
                    "Schema": str(row.get(schema_col, "")).upper(),
                    "Db": str(row.get(db_col, "")).upper(),
                    "ObjType": str(row.get("OBJ_TYPE", "")).upper() if "OBJ_TYPE" in row else "UNKNOWN",
                }
                rows.append(row_out)

        frontier = next_frontier

    return rows


def _fmt_rows(rows: list) -> dict:
    """Convert BFS rows to a result dict with 'upstream' and 'downstream' lists."""
    return {
        "upstream": [r for r in rows if r.get("_direction") == "up"],
        "downstream": [r for r in rows if r.get("_direction") == "down"],
    }


def _make_lineage_info(result: dict, depth: int) -> LineageInfo:
    """Convert a result dict to LineageInfo."""
    upstream = []
    downstream = []

    for row in result.get("upstream", []):
        obj = (
            f"{row.get('Db', '')}.{row.get('Schema', '')}.{row.get('ObjectName', '')}"
            if row.get("Db")
            else f"{row.get('Schema', '')}.{row.get('ObjectName', '')}"
        )
        upstream.append(obj.strip("."))

    for row in result.get("downstream", []):
        obj = (
            f"{row.get('Db', '')}.{row.get('Schema', '')}.{row.get('ObjectName', '')}"
            if row.get("Db")
            else f"{row.get('Schema', '')}.{row.get('ObjectName', '')}"
        )
        downstream.append(obj.strip("."))

    return LineageInfo(upstream=upstream, downstream=downstream)


def make_db_resolver(
    json_path: Optional[str] = None,
    df=None,
    depth: int = 1,
):
    """Resolver backed by a pre-built database snapshot (in-memory BFS, no DB calls).

    Snapshot is loaded once at construction time.

    Args:
        json_path: Path to snapshot JSON. Falls back to env vars if omitted.
        df:        Pre-loaded snapshot DataFrame (takes precedence over json_path).
        depth:     BFS hops to traverse. 1 = direct neighbours, 2 = two levels.

    Returns:
        Callable[[SnowflakeObjectUsage], LineageInfo] for use with resolve_lineage().
    """
    import pandas as pd  # type: ignore[import-not-found]

    if df is None and json_path is None:
        json_path = os.environ.get("DB_SNAPSHOT_PATH") or os.environ.get("CCMS_SNAPSHOT_PATH")

    _df = None
    if df is not None:
        _df = df.copy()
        _df.columns = [c.upper() for c in _df.columns]
    elif json_path:
        json_path = os.path.expanduser(json_path)
    if json_path and _df is None and os.path.exists(json_path):
        _df = pd.read_json(json_path)
        _df.columns = [c.upper() for c in _df.columns]

    def _resolve(usage):
        if _df is None:
            return LineageInfo()
        # Import here to avoid circular dependency
        from .snowflake_metadata import get_lineage
        result = get_lineage(usage.table, df=_df, direction="both", depth=depth)
        return _make_lineage_info(result, depth)

    return _resolve


def make_db_live_resolver(
    query_fn: Callable,
    depth: int = 3,
):
    """Resolver that queries a database directly — no snapshot file needed.

    Args:
        query_fn:  Callable that takes (obj_name, direction, depth) and returns result dict
        depth:     BFS hops. depth=1 = direct neighbours only.

    Returns:
        Callable[[SnowflakeObjectUsage], LineageInfo] for use with resolve_lineage().
    """

    def _resolve(usage):
        if query_fn is None:
            return LineageInfo()
        result = query_fn(usage.table, direction="both", depth=depth)
        return _make_lineage_info(result, depth)

    return _resolve


class DatabaseLineageProvider(DBLineageProvider):
    """Generic database lineage provider using snapshot-based BFS."""

    def __init__(self, snapshot_df):
        """Initialize with a snapshot DataFrame."""
        self.snapshot_df = snapshot_df

    def get_lineage(self, objects: list, direction: str = "both", depth: int = 1) -> LineageResult:
        """Get lineage for a list of objects using snapshot-based BFS."""
        nodes_set = set()
        edges_set = set()

        for obj in objects:
            from .snowflake_metadata import get_lineage
            result = get_lineage(obj, df=self.snapshot_df, direction=direction, depth=depth)

            for row in result.get("upstream", []):
                name = str(row["ObjectName"]).upper()
                if name not in nodes_set:
                    nodes_set.add(name)
                edges_set.add((name, obj))

            for row in result.get("downstream", []):
                name = str(row["ObjectName"]).upper()
                if name not in nodes_set:
                    nodes_set.add(name)
                edges_set.add((obj, name))

        nodes = [{"name": n, "type": "unknown", "depth": 0} for n in nodes_set]
        edges = [{"source": s, "target": t} for s, t in edges_set]

        return LineageResult(nodes=nodes, edges=edges, cycles=[])


import os  # noqa: E402


# Backward-compat aliases
make_ccms_resolver = make_db_resolver
make_ccms_live_resolver = make_db_live_resolver
