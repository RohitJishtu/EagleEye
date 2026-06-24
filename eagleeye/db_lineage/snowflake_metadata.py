"""Snowflake-specific metadata and lineage logic.

Handles:
- Snowflake connection management
- Object dependency queries
- Snapshot creation and loading
- Live lineage queries against Snowflake
- Snowflake provider implementation

Imports database-agnostic BFS utilities from database.py.
"""

from __future__ import annotations

import os
import re as _re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

from .database import _bfs, _build_bfs_indices, _fmt_rows, _make_lineage_info, _validate_obj_name, LineageInfo
from .provider import DBLineageProvider, LineageResult
from .registry import _register

if TYPE_CHECKING:
    pass

# Snowflake-specific queries
_DEPS_QUERY = (
    "SELECT"
    " referenced_database || '.' || referenced_schema"
    " || '.' || referenced_object_name AS OBJECTUSED,"
    " referenced_database AS REFERENCED_DATABASE,"
    " referenced_schema AS REFERENCED_SCHEMA,"
    " referenced_object_name AS REFERENCED_OBJECT_NAME,"
    " referencing_database AS DB,"
    " referencing_schema AS SCHEMA,"
    " referencing_object_name AS OBJ,"
    " referencing_object_domain AS OBJ_TYPE,"
    " dependency_type AS DEPENDENCY_TYPE"
    " FROM snowflake.account_usage.object_dependencies"
)

_QUERIES = {
    "dependencies": _DEPS_QUERY,
    "procedures": "SELECT * FROM EDW_LS.INFORMATION_SCHEMA.PROCEDURES",
    "views": """
        SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, VIEW_DEFINITION
        FROM EDW_LS.INFORMATION_SCHEMA.VIEWS
    """,
    "functions": """
        SELECT FUNCTION_CATALOG, FUNCTION_SCHEMA, FUNCTION_NAME, FUNCTION_DEFINITION
        FROM EDW_LS.INFORMATION_SCHEMA.FUNCTIONS
    """,
}

_SNAPSHOT_FILENAMES = {
    "dependencies": "object_dependencies_snapshot.json",
    "procedures":   "procedures_snapshot.json",
    "views":        "views_snapshot.json",
    "functions":    "functions_snapshot.json",
}

# Snowflake returns SQL aliases as UPPERCASE; map back to the mixed-case keys
_LIVE_COL_NAMES = {
    "OBJECTNAME":      "ObjectName",
    "OBJTYPE":         "ObjType",
    "SCHEMA":          "Schema",
    "DB":              "Db",
    "DEPENDENCYTYPE":  "DependencyType",
    "STARTING_OBJECT": "STARTING_OBJECT",
}


def get_connection(
    user: str,
    account: str,
    authenticator: str = "externalbrowser",
    database: str = "EDW_LS",
    warehouse: str = "DS_STD_WH",
    role: str = "DS_ROLE",
    password: Optional[str] = None,
):
    """Create and return a Snowflake connection.

    Args:
        user:          Snowflake username (e.g. "you@company.com").
        account:       Snowflake account identifier (e.g. "myorg-myaccount").
        authenticator: "externalbrowser" (SSO, default) or "snowflake" for password.
        database:      Default database to use after connecting.
        warehouse:     Default warehouse.
        role:          Role to activate after connecting.
        password:      Required only when authenticator="snowflake".

    Returns:
        An open snowflake.connector.SnowflakeConnection.
    """
    import snowflake.connector  # type: ignore[import-not-found]

    connect_kwargs: dict = dict(
        user=user,
        account=account,
        authenticator=authenticator,
        database=database,
        warehouse=warehouse,
    )
    if password is not None:
        connect_kwargs["password"] = password

    conn = snowflake.connector.connect(**connect_kwargs)

    # Fix: close connection on failure to prevent leaks
    try:
        cur = conn.cursor()
        try:
            if role:
                cur.execute(f"USE ROLE {role}")
            if database:
                cur.execute(f"USE DATABASE {database}")
            if warehouse:
                cur.execute(f"USE WAREHOUSE {warehouse}")
        finally:
            cur.close()
    except Exception:
        conn.close()
        raise

    return conn


def _run_query_to_json(conn, query: str, out_path: str) -> int:
    """Execute query and write results as JSON. Returns row count."""
    import pandas as pd  # type: ignore[import-not-found]

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    cur = conn.cursor()
    try:
        cur.execute(query)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=cols)
    finally:
        cur.close()
    df.to_json(out_path, orient="records", indent=2)
    return len(df)


def refresh_metadata(
    conn,
    *,
    dependencies: bool = False,
    procedures: bool = False,
    views: bool = False,
    functions: bool = False,
    base_dir: str,
) -> dict:
    """Pull Snowflake metadata to local JSON snapshots.

    Safe to call on the very first run — creates the output directory and
    files if they do not yet exist.

    Args:
        conn:         Open Snowflake connection (from get_connection).
        dependencies: Refresh object_dependencies_snapshot.json.
        procedures:   Refresh procedures_snapshot.json.
        views:        Refresh views_snapshot.json.
        functions:    Refresh functions_snapshot.json.
        base_dir:     Directory where snapshot JSON files are written.

    Returns:
        Dict of {snapshot_name: file_path} for each snapshot that was refreshed.
    """
    flags = {
        "dependencies": dependencies,
        "procedures":   procedures,
        "views":        views,
        "functions":    functions,
    }

    refreshed = {}
    for name, enabled in flags.items():
        if not enabled:
            continue
        out_path = os.path.join(base_dir, _SNAPSHOT_FILENAMES[name])
        action = "Creating" if not os.path.exists(out_path) else "Refreshing"
        print(f"[refresh_metadata] {action} {name} -> {out_path}", flush=True)
        n = _run_query_to_json(conn, _QUERIES[name], out_path)
        print(f"[refresh_metadata]   {n} rows written", flush=True)
        refreshed[name] = out_path

    if not refreshed:
        print("[refresh_metadata] No snapshots selected (all flags are False).", flush=True)

    return refreshed


def _load_snapshot(json_path: str):
    """Load a JSON snapshot into a DataFrame with uppercased columns."""
    import pandas as pd  # type: ignore[import-not-found]

    df = pd.read_json(json_path)
    df.columns = [c.upper() for c in df.columns]
    return df


def get_lineage(
    object_name: str,
    df=None,
    json_path: Optional[str] = None,
    direction: Literal["upstream", "downstream", "both"] = "both",
    depth: int = 1,
) -> dict:
    """Return upstream and/or downstream lineage for a Snowflake object.

    Upstream   = objects that `object_name` depends on (it references them).
    Downstream = objects that depend on `object_name` (they reference it).

    Args:
        object_name: Starting object name (case-insensitive).
        df:          Pre-loaded snapshot DataFrame. Takes precedence over json_path.
        json_path:   Path to object_dependencies_snapshot.json.
        direction:   "upstream", "downstream", or "both".
        depth:       Hops to traverse. depth=1 = direct neighbours only.

    Returns:
        {
          "upstream":   [{ObjectName, ObjType, Schema, Db, DependencyType, Hop}, ...],
          "downstream": [{ObjectName, ObjType, Schema, Db, DependencyType, Hop}, ...],
        }
        The key for the unused direction contains an empty list.
    """
    if df is None and json_path is None:
        raise ValueError("Provide either df or json_path.")

    if df is None:
        if not os.path.exists(json_path):  # type: ignore[arg-type]
            raise FileNotFoundError(
                f"Snapshot not found: {json_path}\n"
                "Run refresh_metadata(..., dependencies=True) first to create it."
            )
        df = _load_snapshot(json_path)  # type: ignore[arg-type]
    else:
        df = df.copy()
        df.columns = [c.upper() for c in df.columns]

    root = object_name.upper()
    result: dict = {"upstream": [], "downstream": []}

    if direction in ("upstream", "both"):
        result["upstream"] = _bfs(df, root, mode="upstream", depth=depth)

    if direction in ("downstream", "both"):
        result["downstream"] = _bfs(df, root, mode="downstream", depth=depth)

    return result


def lineage_to_dataframe(lineage_list: list):
    """Convert a get_lineage result list into a pandas DataFrame."""
    import pandas as pd  # type: ignore[import-not-found]

    if not lineage_list:
        return pd.DataFrame(
            columns=["ObjectName", "ObjType", "Schema", "Db", "DependencyType", "Hop"]
        )
    return pd.DataFrame(lineage_list)


def _bfs_live(
    conn,
    start: str,
    mode: str,
    depth: int,
) -> list:
    """BFS over object_dependencies via live Snowflake queries.

    mode='upstream'   — objects that `start` references (its dependencies)
    mode='downstream' — objects that reference `start` (its dependents)
    Each hop issues one query against snowflake.account_usage.object_dependencies.
    """
    visited = {start}
    frontier = [start]
    rows = []

    for hop in range(1, depth + 1):
        if not frontier:
            break

        placeholders = ", ".join(f"'{_validate_obj_name(obj)}'" for obj in frontier)

        if mode == "upstream":
            query = f"""
                SELECT
                    referenced_object_name  AS ObjectName,
                    referencing_object_domain AS ObjType,
                    referenced_schema        AS Schema,
                    referenced_database      AS Db,
                    dependency_type          AS DependencyType
                FROM snowflake.account_usage.object_dependencies
                WHERE UPPER(referencing_object_name) IN ({placeholders})
            """
        else:
            query = f"""
                SELECT
                    referencing_object_name   AS ObjectName,
                    referencing_object_domain AS ObjType,
                    referencing_schema        AS Schema,
                    referencing_database      AS Db,
                    dependency_type           AS DependencyType
                FROM snowflake.account_usage.object_dependencies
                WHERE UPPER(referenced_object_name) IN ({placeholders})
            """

        cur = conn.cursor()
        try:
            cur.execute(query)
            cols = [_LIVE_COL_NAMES.get(c[0].upper(), c[0]) for c in cur.description]
            batch = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            cur.close()

        next_frontier = []
        for row in batch:
            neighbour = str(row["ObjectName"]).upper()
            if neighbour in visited:
                continue
            visited.add(neighbour)
            next_frontier.append(neighbour)
            rows.append({**row, "Hop": hop})

        frontier = next_frontier

    return rows


def get_lineage_live(
    conn,
    object_name: str,
    direction: Literal["upstream", "downstream", "both"] = "both",
    depth: int = 1,
) -> dict:
    """Query Snowflake directly for upstream/downstream lineage of an object.

    Unlike get_lineage(), this requires no pre-built snapshot — it queries
    snowflake.account_usage.object_dependencies at call time.
    Each hop issues one query; depth=2 issues up to 4 queries total.

    Args:
        conn:        Open Snowflake connection (from get_connection).
        object_name: Starting object name (case-insensitive).
        direction:   "upstream", "downstream", or "both".
        depth:       Hops to traverse. depth=1 = direct neighbours only.

    Returns:
        {
          "upstream":   [{ObjectName, ObjType, Schema, Db, DependencyType, Hop}, ...],
          "downstream": [{ObjectName, ObjType, Schema, Db, DependencyType, Hop}, ...],
        }
    """
    root = object_name.upper()
    result: dict = {"upstream": [], "downstream": []}

    if direction in ("upstream", "both"):
        result["upstream"] = _bfs_live(conn, root, mode="upstream", depth=depth)

    if direction in ("downstream", "both"):
        result["downstream"] = _bfs_live(conn, root, mode="downstream", depth=depth)

    return result


def _bfs_live_batch(
    conn,
    starts: list[str],
    mode: str,
    depth: int,
) -> dict[str, list]:
    """BFS for multiple starting objects using one IN-clause query per hop.

    Returns {start_object_upper: [rows]} instead of a flat list.
    For N objects at depth D this issues D queries instead of N*D queries.

    Fix: _validate_obj_name() is called on every object before interpolation
    into the IN-clause to prevent SQL injection.
    """
    starts = [_validate_obj_name(s) for s in starts]
    object_results: dict[str, list] = {s: [] for s in starts}
    object_frontiers: dict[str, set] = {s: {s} for s in starts}
    all_visited: dict[str, set] = {s: {s} for s in starts}

    for hop in range(1, depth + 1):
        all_frontier: set[str] = set()
        for frontier in object_frontiers.values():
            all_frontier.update(frontier)
        if not all_frontier:
            break

        # Validate every node before building the IN-clause
        safe_frontier = {_validate_obj_name(obj) for obj in all_frontier}
        placeholders = ", ".join(f"'{obj}'" for obj in safe_frontier)

        if mode == "upstream":
            query = f"""
                SELECT UPPER(referencing_object_name) AS STARTING_OBJECT,
                       referenced_object_name         AS ObjectName,
                       referencing_object_domain      AS ObjType,
                       referenced_schema              AS Schema,
                       referenced_database            AS Db,
                       dependency_type                AS DependencyType
                FROM snowflake.account_usage.object_dependencies
                WHERE UPPER(referencing_object_name) IN ({placeholders})
            """
        else:
            query = f"""
                SELECT UPPER(referenced_object_name)  AS STARTING_OBJECT,
                       referencing_object_name        AS ObjectName,
                       referencing_object_domain      AS ObjType,
                       referencing_schema             AS Schema,
                       referencing_database           AS Db,
                       dependency_type                AS DependencyType
                FROM snowflake.account_usage.object_dependencies
                WHERE UPPER(referenced_object_name) IN ({placeholders})
            """

        cur = conn.cursor()
        try:
            cur.execute(query)
            cols = [_LIVE_COL_NAMES.get(c[0].upper(), c[0]) for c in cur.description]
            batch = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            cur.close()

        # Build reverse index: frontier_node -> which start objects own it
        frontier_to_starts: dict[str, list[str]] = {}
        for start, frontier in object_frontiers.items():
            for node in frontier:
                frontier_to_starts.setdefault(node, []).append(start)

        next_frontiers: dict[str, set] = {s: set() for s in starts}
        for row in batch:
            src = row["STARTING_OBJECT"]
            neighbour = str(row["ObjectName"]).upper()
            for start in frontier_to_starts.get(src, []):
                if neighbour not in all_visited[start]:
                    all_visited[start].add(neighbour)
                    next_frontiers[start].add(neighbour)
                    result_row = {k: v for k, v in row.items() if k != "STARTING_OBJECT"}
                    result_row["Hop"] = hop
                    object_results[start].append(result_row)

        object_frontiers = next_frontiers

    return object_results


def get_lineage_live_batch(
    conn,
    object_names: list[str],
    direction: Literal["upstream", "downstream", "both"] = "both",
    depth: int = 1,
) -> dict[str, dict]:
    """Batched version of get_lineage_live — resolves all objects in 2 queries per hop.

    Args:
        conn:         Open Snowflake connection.
        object_names: List of object names to resolve (case-insensitive).
        direction:    "upstream", "downstream", or "both".
        depth:        BFS hops. depth=1 = direct neighbours only.

    Returns:
        {object_name_upper: {"upstream": [...], "downstream": [...]}}
        Same row shape as get_lineage_live, keyed by uppercased object name.
    """
    roots = [_validate_obj_name(n) for n in object_names]
    result: dict[str, dict] = {r: {"upstream": [], "downstream": []} for r in roots}

    if direction in ("upstream", "both"):
        for root, rows in _bfs_live_batch(conn, roots, "upstream", depth).items():
            result[root]["upstream"] = rows

    if direction in ("downstream", "both"):
        for root, rows in _bfs_live_batch(conn, roots, "downstream", depth).items():
            result[root]["downstream"] = rows

    return result


def make_db_resolver(
    json_path: Optional[str] = None,
    df=None,
    depth: int = 1,
):
    """Resolver backed by a pre-built Snowflake snapshot (in-memory BFS, no DB calls).

    Snapshot is loaded once at construction time.

    Args:
        json_path: Path to object_dependencies_snapshot.json. Falls back to env vars.
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
        result = get_lineage(usage.table, df=_df, direction="both", depth=depth)
        return _make_lineage_info(result, depth)

    return _resolve


def make_db_live_resolver(
    conn=None,
    depth: int = 3,
):
    """Resolver that queries Snowflake directly — no snapshot file needed.

    Args:
        conn:  Open SnowflakeConnection (from get_connection()).
               If omitted, creates one from DB_SF_USER + DB_SF_ACCOUNT env vars.
        depth: BFS hops. depth=1 = direct neighbours only.

    Returns:
        Callable[[SnowflakeObjectUsage], LineageInfo] for use with resolve_lineage().
    """
    _conn = conn
    if _conn is None:
        user = os.environ.get("DB_SF_USER") or os.environ.get("CCMS_SF_USER")
        account = os.environ.get("DB_SF_ACCOUNT") or os.environ.get("CCMS_SF_ACCOUNT")
        if user and account:
            _conn = get_connection(user=user, account=account)

    def _resolve(usage):
        if _conn is None:
            return LineageInfo()
        result = get_lineage_live(_conn, usage.table, direction="both", depth=depth)
        return _make_lineage_info(result, depth)

    return _resolve


def get_db_connection(user: Optional[str] = None, account: Optional[str] = None):
    """Create a Snowflake connection from args or DB_SF_USER/DB_SF_ACCOUNT env vars.

    Returns None if credentials are not available (so callers can skip gracefully).
    """
    user = user or os.environ.get("DB_SF_USER") or os.environ.get("CCMS_SF_USER")
    account = account or os.environ.get("DB_SF_ACCOUNT") or os.environ.get("CCMS_SF_ACCOUNT")
    if not user or not account:
        return None
    try:
        return get_connection(user=user, account=account)
    except ImportError:
        return None


def resolve_lineage_batch(
    extract,
    conn,
    depth: int = 1,
):
    """Resolve lineage for all Snowflake objects in the extract using batched queries.

    Issues 2 queries per hop (one upstream IN-clause, one downstream IN-clause)
    regardless of how many objects are in the extract.

    Args:
        extract: Output of extract_snowflake_usages().
        conn:    Open SnowflakeConnection (from get_db_connection() or get_connection()).
        depth:   BFS hops. depth=1 = direct neighbours only.

    Returns:
        The same extract with upstream/downstream populated on every usage.
    """
    tables = list({u.table.upper() for u in extract.usages if u.table})
    if not tables:
        return extract

    all_lineage = get_lineage_live_batch(conn, tables, direction="both", depth=depth)

    for usage in extract.usages:
        key = usage.table.upper()
        lineage = all_lineage.get(key, {"upstream": [], "downstream": []})
        info = _make_lineage_info(lineage, depth)
        usage.upstream = info.upstream
        usage.downstream = info.downstream
        usage.lineage_note = info.note

    return extract


class SnowflakeLineageProvider(DBLineageProvider):
    """DBLineageProvider backed by a Snowflake snapshot or live connection.

    Implements the abstract interface defined in eagleeye/db_lineage/provider.py.

    Usage (snapshot mode):
        provider = SnowflakeLineageProvider(json_path="/snapshots/deps.json")
        result = provider.get_lineage(["U_CAMPAIGN", "ACCOUNT_METRICS"], direction="both", depth=2)

    Usage (live mode):
        conn = get_connection(user="you@company.com", account="myorg-myaccount")
        provider = SnowflakeLineageProvider(conn=conn)
        result = provider.get_lineage(["U_CAMPAIGN"], direction="downstream", depth=3)
    """

    def __init__(
        self,
        json_path: Optional[str] = None,
        df=None,
        conn=None,
    ) -> None:
        self._json_path = json_path
        self._df = df
        self._conn = conn

    def get_lineage(
        self,
        objects: list[str],
        direction: str = "both",
        depth: int = 3,
    ) -> LineageResult:
        """Return upstream/downstream lineage as a LineageResult.

        Prefer snapshot (json_path / df) when available; fall back to live conn.
        """
        nodes: list[dict] = []
        edges: list[dict] = []
        seen_nodes: set[str] = set()

        for obj_name in objects:
            root = obj_name.upper()

            if self._conn is not None:
                raw = get_lineage_live(self._conn, root, direction=direction, depth=depth)  # type: ignore[arg-type]
            else:
                raw = get_lineage(
                    root,
                    df=self._df,
                    json_path=self._json_path,
                    direction=direction,  # type: ignore[arg-type]
                    depth=depth,
                )

            # Seed root node
            if root not in seen_nodes:
                seen_nodes.add(root)
                nodes.append({"name": root, "type": "unknown", "depth": 0})

            for row in raw.get("upstream", []):
                name = str(row["ObjectName"]).upper()
                if name not in seen_nodes:
                    seen_nodes.add(name)
                    nodes.append(
                        {"name": name, "type": row.get("ObjType") or "unknown", "depth": row["Hop"]}
                    )
                edges.append({"source": name, "target": root})

            for row in raw.get("downstream", []):
                name = str(row["ObjectName"]).upper()
                if name not in seen_nodes:
                    seen_nodes.add(name)
                    nodes.append(
                        {"name": name, "type": row.get("ObjType") or "unknown", "depth": row["Hop"]}
                    )
                edges.append({"source": root, "target": name})

        return LineageResult(nodes=nodes, edges=edges, cycles=[])


# Backward-compat aliases
make_ccms_resolver = make_db_resolver
make_ccms_live_resolver = make_db_live_resolver
get_ccms_connection = get_db_connection


_register("snowflake", SnowflakeLineageProvider)
