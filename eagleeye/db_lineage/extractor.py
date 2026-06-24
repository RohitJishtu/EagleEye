"""Snowflake object usage extractor for EDP lineage analysis.

Scans ONLY the files that changed in the diff — not the full repo.
For each changed file, extracts every Snowflake object reference and
classifies the operation:

  READ   — SELECT FROM, JOIN, spark.read, jdbc read
  WRITE  — INSERT INTO, MERGE INTO, UPDATE, spark.write, saveAsTable
  CREATE — CREATE TABLE, CREATE VIEW, CREATE OR REPLACE
  DROP   — DROP TABLE, DROP VIEW
  ALTER  — ALTER TABLE ADD/DROP/RENAME COLUMN

Returns a SnowflakeUsageExtract that you can:
  1. Feed directly to the EDP agent as pre-computed lineage context
  2. Pass to your own resolve_lineage() function to add upstream/downstream
     dependency information before the agent sees it

Hook point for custom dependency resolution:
  Register a callable via SnowflakeUsageExtract.set_lineage_resolver(fn)
  or call resolve_lineage(extract, your_fn) directly.
  Your function receives a SnowflakeObjectUsage and returns
  LineageInfo(upstream=[...], downstream=[...]).
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class SnowflakeObjectUsage:
    """A single usage of a Snowflake object in a changed file."""
    # Object identity
    raw_ref: str            # exactly as it appears in code: "AIML_DATA.ACCOUNT.METRICS"
    catalog: str            # "" if not present
    schema: str             # "" if not present
    table: str              # the object name itself

    # Operation
    operation: str          # READ | WRITE | CREATE | DROP | ALTER

    # Location
    file: str
    line: int
    snippet: str            # the source line (truncated)
    context: str            # "sql" | "pyspark" | "yaml" | "notebook" | "config"

    # Dependency info — populated by your lineage resolver
    upstream: list[str] = field(default_factory=list)    # where data comes FROM
    downstream: list[str] = field(default_factory=list)  # where data goes TO
    lineage_note: str = ""


@dataclass
class SnowflakeUsageExtract:
    """All Snowflake object usages found across changed files."""
    usages: list[SnowflakeObjectUsage] = field(default_factory=list)
    changed_files_scanned: list[str] = field(default_factory=list)
    files_with_hits: list[str] = field(default_factory=list)

    # Convenience views
    @property
    def reads(self) -> list[SnowflakeObjectUsage]:
        return [u for u in self.usages if u.operation == "READ"]

    @property
    def writes(self) -> list[SnowflakeObjectUsage]:
        return [u for u in self.usages if u.operation == "WRITE"]

    @property
    def ddl(self) -> list[SnowflakeObjectUsage]:
        return [u for u in self.usages if u.operation in ("CREATE", "DROP", "ALTER")]

    @property
    def objects_touched(self) -> list[str]:
        """Deduplicated list of all objects referenced."""
        seen: set[str] = set()
        result = []
        for u in self.usages:
            key = u.raw_ref.upper()
            if key not in seen:
                seen.add(key)
                result.append(u.raw_ref)
        return result


# Fix 1: Tightened to require schema-qualified names (at least one dot).
# This prevents bare SQL keywords like STATUS, COUNT, CATEGORY from matching.
_OBJ_NAME_RE = re.compile(
    r'\b([A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*(?:\.[A-Z][A-Z0-9_]*)?)\b',
    re.IGNORECASE,
)

# Known non-table SQL keywords to skip when bare names are detected
_SQL_KEYWORDS = frozenset({
    "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL",
    "ON", "AND", "OR", "NOT", "IN", "IS", "NULL", "AS", "BY", "GROUP", "ORDER",
    "HAVING", "LIMIT", "OFFSET", "UNION", "ALL", "DISTINCT", "CASE", "WHEN",
    "THEN", "ELSE", "END", "WITH", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
    "DELETE", "MERGE", "USING", "MATCHED", "CREATE", "DROP", "ALTER", "TABLE",
    "VIEW", "REPLACE", "IF", "EXISTS", "NOT", "ADD", "COLUMN", "RENAME", "TO",
    "TRUE", "FALSE", "NULL", "LIKE", "BETWEEN", "OVER", "PARTITION", "ROWS",
    "RANGE", "UNBOUNDED", "FOLLOWING", "PRECEDING", "CURRENT", "ROW",
    "CATALOG", "SCHEMA", "DATABASE", "USE", "SHOW", "DESCRIBE", "EXPLAIN",
    "BEGIN", "COMMIT", "ROLLBACK", "TRANSACTION", "GRANT", "REVOKE",
    "COPY", "INTO", "FROM", "STAGE", "FORMAT", "OPTIONS",
})


def _parse_object_name(raw: str) -> tuple[str, str, str]:
    """
    Parse a raw object reference into (catalog, schema, table).
    Returns ("", "", "") if it looks like a keyword.
    """
    # Strip quotes
    clean = raw.replace('"', '').replace('`', '')
    parts = [p.strip() for p in clean.split('.')]

    if len(parts) == 3:
        return parts[0].upper(), parts[1].upper(), parts[2].upper()
    elif len(parts) == 2:
        return "", parts[0].upper(), parts[1].upper()
    elif len(parts) == 1:
        name = parts[0].upper()
        if name in _SQL_KEYWORDS or len(name) < 3:
            return "", "", ""
        return "", "", name
    return "", "", ""


def _build_line_offsets(content: str) -> list[int]:
    """Build a list of character offsets where each line starts."""
    offsets = [0]
    for i, ch in enumerate(content):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def _offset_to_lineno(offsets: list[int], offset: int) -> int:
    """Return 1-based line number for a given character offset using binary search."""
    return bisect.bisect_right(offsets, offset)


# ----- SQL patterns -----

# READ: FROM/JOIN clauses — the object after FROM or JOIN keyword
_SQL_READ_RE = re.compile(
    r'\b(?:FROM|JOIN)\s+(["`]?[A-Za-z_][A-Za-z0-9_]*["`]?'
    r'(?:\.["`]?[A-Za-z_][A-Za-z0-9_]*["`]?){0,2})',
    re.IGNORECASE,
)

# WRITE: INSERT INTO, MERGE INTO, UPDATE
_SQL_WRITE_RE = re.compile(
    r'\b(?:INSERT\s+(?:OVERWRITE\s+)?INTO|MERGE\s+INTO|UPDATE)\s+'
    r'(["`]?[A-Za-z_][A-Za-z0-9_]*["`]?(?:\.["`]?[A-Za-z_][A-Za-z0-9_]*["`]?){0,2})',
    re.IGNORECASE,
)

# CREATE TABLE / VIEW
_SQL_CREATE_RE = re.compile(
    r'\b(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|TRANSIENT\s+TABLE))'
    r'\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    r'(["`]?[A-Za-z_][A-Za-z0-9_]*["`]?(?:\.["`]?[A-Za-z_][A-Za-z0-9_]*["`]?){0,2})',
    re.IGNORECASE,
)

# DROP TABLE / VIEW
_SQL_DROP_RE = re.compile(
    r'\bDROP\s+(?:TABLE|VIEW)\s+(?:IF\s+EXISTS\s+)?'
    r'(["`]?[A-Za-z_][A-Za-z0-9_]*["`]?(?:\.["`]?[A-Za-z_][A-Za-z0-9_]*["`]?){0,2})',
    re.IGNORECASE,
)

# ALTER TABLE
_SQL_ALTER_RE = re.compile(
    r'\bALTER\s+TABLE\s+'
    r'(["`]?[A-Za-z_][A-Za-z0-9_]*["`]?(?:\.["`]?[A-Za-z_][A-Za-z0-9_]*["`]?){0,2})',
    re.IGNORECASE,
)

# COPY INTO (Snowflake-specific bulk load)
_SQL_COPY_RE = re.compile(
    r'\bCOPY\s+INTO\s+'
    r'(["`]?[A-Za-z_][A-Za-z0-9_]*["`]?(?:\.["`]?[A-Za-z_][A-Za-z0-9_]*["`]?){0,2})',
    re.IGNORECASE,
)

# ----- PySpark / Python patterns -----

# spark.read.table("catalog.schema.table")
_PY_READ_TABLE_RE = re.compile(
    r'(?:spark|session|sc)\.read(?:Stream)?\s*\.\s*(?:table|load)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# spark.sql("SELECT ... FROM table")  — extract the SQL string and re-parse
_PY_SPARK_SQL_RE = re.compile(
    r'(?:spark|session|sc|sql)\s*\.\s*sql\s*\(\s*["\'{](.*?)["\'}]\s*\)',
    re.IGNORECASE | re.DOTALL,
)

# df.write.saveAsTable("catalog.schema.table")
_PY_WRITE_TABLE_RE = re.compile(
    r'\.(?:saveAsTable|insertInto)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# df.write.format(...).save("path")  — path-based writes (less precise)
_PY_WRITE_SAVE_RE = re.compile(
    r'\.write(?:Stream)?\s*(?:\.[^(]+\([^)]*\))*\s*\.save\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# jdbc read: spark.read.jdbc(url, "schema.table", ...)
_PY_JDBC_READ_RE = re.compile(
    r'\.jdbc\s*\([^,]+,\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# DeltaTable.forName("catalog.schema.table")
_PY_DELTA_RE = re.compile(
    r'DeltaTable\s*\.\s*forName\s*\(\s*[^,)]*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# ----- YAML config patterns -----

# table_name: MY_TABLE  /  target_table: ...  /  source_table: ...
_YAML_TABLE_RE = re.compile(
    r'(?:table_name|target_table|source_table|output_table|input_table'
    r'|catalog_table|snowflake_table|destination)\s*:\s*["\']?([A-Za-z_][A-Za-z0-9_.]*)["\']?',
    re.IGNORECASE,
)


def _context_for_file(path: str) -> str:
    p = path.lower()
    if p.endswith(".sql") or p.endswith(".ddl") or p.endswith(".hql"):
        return "sql"
    if p.endswith(".py"):
        return "pyspark"
    if p.endswith((".yml", ".yaml")):
        return "yaml"
    if p.endswith(".ipynb"):
        return "notebook"
    return "config"


def _extract_from_sql(file_path: str, lines: list[str]) -> list[SnowflakeObjectUsage]:
    usages: list[SnowflakeObjectUsage] = []
    full_text = "\n".join(lines)
    # Fix 4: build offsets once, then use O(log n) lookup per match
    offsets = _build_line_offsets(full_text)

    rule_sets = [
        (_SQL_READ_RE, "READ"),
        (_SQL_WRITE_RE, "WRITE"),
        (_SQL_CREATE_RE, "CREATE"),
        (_SQL_DROP_RE, "DROP"),
        (_SQL_ALTER_RE, "ALTER"),
        (_SQL_COPY_RE, "WRITE"),
    ]

    for pattern, operation in rule_sets:
        for match in pattern.finditer(full_text):
            raw_ref = match.group(1).strip()
            catalog, schema, table = _parse_object_name(raw_ref)
            if not table:
                continue
            # Fix 4: O(log n) line number lookup
            line_no = _offset_to_lineno(offsets, match.start())
            snippet = lines[line_no - 1].strip()[:120] if line_no <= len(lines) else ""
            usages.append(SnowflakeObjectUsage(
                raw_ref=raw_ref,
                catalog=catalog, schema=schema, table=table,
                operation=operation,
                file=file_path, line=line_no,
                snippet=snippet, context="sql",
            ))

    return usages


def _extract_from_python(file_path: str, lines: list[str]) -> list[SnowflakeObjectUsage]:
    usages: list[SnowflakeObjectUsage] = []
    full_text = "\n".join(lines)
    # Fix 4: build offsets once, then use O(log n) lookup per match
    offsets = _build_line_offsets(full_text)

    # Explicit table reads
    for match in _PY_READ_TABLE_RE.finditer(full_text):
        raw_ref = match.group(1).strip()
        catalog, schema, table = _parse_object_name(raw_ref)
        if not table:
            continue
        line_no = _offset_to_lineno(offsets, match.start())
        usages.append(SnowflakeObjectUsage(
            raw_ref=raw_ref, catalog=catalog, schema=schema, table=table,
            operation="READ", file=file_path, line=line_no,
            snippet=lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
            context="pyspark",
        ))

    # spark.sql("...") — re-parse the embedded SQL
    for match in _PY_SPARK_SQL_RE.finditer(full_text):
        line_no = _offset_to_lineno(offsets, match.start())
        # Fix 3: if it's an f-string, flag as dynamic rather than trying to extract SQL
        src_line = lines[line_no - 1] if line_no <= len(lines) else ""
        if 'f"' in src_line or "f'" in src_line:
            usages.append(SnowflakeObjectUsage(
                raw_ref="<dynamic SQL — table name unknown>",
                catalog="", schema="", table="<dynamic SQL — table name unknown>",
                operation="READ", file=file_path, line=line_no,
                snippet=src_line.strip()[:120],
                context="pyspark",
            ))
            continue

        sql_str = match.group(1)
        sql_lines = sql_str.splitlines()
        for sub in _extract_from_sql(file_path, sql_lines):
            sub.line = line_no
            sub.context = "pyspark"
            usages.append(sub)

    # Write: saveAsTable
    for match in _PY_WRITE_TABLE_RE.finditer(full_text):
        raw_ref = match.group(1).strip()
        catalog, schema, table = _parse_object_name(raw_ref)
        if not table:
            continue
        line_no = _offset_to_lineno(offsets, match.start())
        usages.append(SnowflakeObjectUsage(
            raw_ref=raw_ref, catalog=catalog, schema=schema, table=table,
            operation="WRITE", file=file_path, line=line_no,
            snippet=lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
            context="pyspark",
        ))

    # JDBC reads
    for match in _PY_JDBC_READ_RE.finditer(full_text):
        raw_ref = match.group(1).strip()
        catalog, schema, table = _parse_object_name(raw_ref)
        if not table:
            continue
        line_no = _offset_to_lineno(offsets, match.start())
        usages.append(SnowflakeObjectUsage(
            raw_ref=raw_ref, catalog=catalog, schema=schema, table=table,
            operation="READ", file=file_path, line=line_no,
            snippet=lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
            context="pyspark",
        ))

    # DeltaTable.forName
    for match in _PY_DELTA_RE.finditer(full_text):
        raw_ref = match.group(1).strip()
        catalog, schema, table = _parse_object_name(raw_ref)
        if not table:
            continue
        line_no = _offset_to_lineno(offsets, match.start())
        usages.append(SnowflakeObjectUsage(
            raw_ref=raw_ref, catalog=catalog, schema=schema, table=table,
            operation="READ", file=file_path, line=line_no,
            snippet=lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
            context="pyspark",
        ))

    return usages


def _extract_from_yaml(file_path: str, lines: list[str]) -> list[SnowflakeObjectUsage]:
    usages: list[SnowflakeObjectUsage] = []
    for i, line in enumerate(lines, 1):
        for match in _YAML_TABLE_RE.finditer(line):
            raw_ref = match.group(1).strip()
            catalog, schema, table = _parse_object_name(raw_ref)
            if not table:
                continue
            # Infer operation from key name
            key = match.group(0).split(":")[0].lower()
            if any(k in key for k in ("target", "output", "destination", "write")):
                op = "WRITE"
            elif any(k in key for k in ("source", "input", "read")):
                op = "READ"
            else:
                op = "READ"   # conservative default for config refs
            usages.append(SnowflakeObjectUsage(
                raw_ref=raw_ref, catalog=catalog, schema=schema, table=table,
                operation=op, file=file_path, line=i,
                snippet=line.strip()[:120], context="yaml",
            ))
    return usages


def _get_changed_files(diff: str) -> list[str]:
    """Return list of file paths that were modified in the diff."""
    files = []
    for line in diff.splitlines():
        # Fix 2: Only add if it's a real file, not /dev/null (deleted file diffs)
        if line.startswith("+++ b/") and not line.startswith("+++ b/dev/null"):
            files.append(line[6:])
    return files


def _dedup_usages(usages: list[SnowflakeObjectUsage]) -> list[SnowflakeObjectUsage]:
    """Remove duplicate (object, operation, file, line) entries."""
    seen: set[tuple] = set()
    result = []
    for u in usages:
        key = (u.table.upper(), u.operation, u.file, u.line)
        if key not in seen:
            seen.add(key)
            result.append(u)
    return result


def _infer_pr_lineage(usages: list[SnowflakeObjectUsage]) -> None:
    """Infer upstream/downstream relationships from within the PR itself.

    Logic: if file F creates object Y and reads from object X, and object X is
    also created somewhere in this PR, then X → Y (Y is downstream of X).

    This handles the common pattern where a PR adds both a base table and a view
    that selects from it — the snapshot can't know about these new objects, but
    the relationship is visible in the diff.
    """
    # Map: normalised object ref → usage (prefer CREATE/ALTER entries)
    created: dict[str, SnowflakeObjectUsage] = {}
    for u in usages:
        if u.operation in ("CREATE", "ALTER"):
            key = u.raw_ref.upper()
            created[key] = u

    # For each file, collect what it creates and what it reads
    from collections import defaultdict
    file_creates: dict[str, list[str]] = defaultdict(list)   # file → [raw_ref created]
    file_reads: dict[str, list[str]]   = defaultdict(list)   # file → [raw_ref read]

    for u in usages:
        if u.operation in ("CREATE", "ALTER"):
            file_creates[u.file].append(u.raw_ref.upper())
        elif u.operation in ("READ", "WRITE"):
            file_reads[u.file].append(u.raw_ref.upper())

    # Wire up: for each file that creates Y and reads X (where X is also created
    # in this PR), mark X as upstream of Y and Y as downstream of X.
    for file, creates in file_creates.items():
        reads = file_reads.get(file, [])
        for created_ref in creates:
            for read_ref in reads:
                if read_ref in created and read_ref != created_ref:
                    # read_ref is upstream of created_ref
                    upstream_usage  = created[read_ref]
                    downstream_usage = created[created_ref]
                    if downstream_usage.raw_ref not in upstream_usage.downstream:
                        upstream_usage.downstream.append(downstream_usage.raw_ref)
                    if upstream_usage.raw_ref not in downstream_usage.upstream:
                        downstream_usage.upstream.append(upstream_usage.raw_ref)


def extract_snowflake_usages(
    diff: str,
    file_contents: dict[str, str],
) -> SnowflakeUsageExtract:
    """
    Extract all Snowflake object usages from CHANGED FILES ONLY.

    Parameters
    ----------
    diff          : raw unified diff string
    file_contents : dict of {file_path: content} for fetched files

    Returns
    -------
    SnowflakeUsageExtract with usages classified as READ / WRITE / CREATE / DROP / ALTER.
    Each usage has upstream=[] and downstream=[] ready to be filled by your
    resolve_lineage() function before the EDP agent sees the data.
    """
    extract = SnowflakeUsageExtract()
    changed_files = _get_changed_files(diff)
    extract.changed_files_scanned = changed_files

    for file_path in changed_files:
        content = file_contents.get(file_path, "")
        if not content:
            continue

        lines = content.splitlines()
        ctx = _context_for_file(file_path)

        if ctx == "sql":
            usages = _extract_from_sql(file_path, lines)
        elif ctx == "pyspark":
            usages = _extract_from_python(file_path, lines)
        elif ctx == "yaml":
            usages = _extract_from_yaml(file_path, lines)
        elif ctx == "notebook":
            # Notebooks mix SQL cells and Python cells — run both extractors
            usages = _extract_from_python(file_path, lines)
            usages += _extract_from_sql(file_path, lines)
        else:
            usages = []

        if usages:
            extract.files_with_hits.append(file_path)
            extract.usages.extend(usages)

    extract.usages = _dedup_usages(extract.usages)
    return extract


@dataclass
class LineageInfo:
    """
    Your function returns this for each SnowflakeObjectUsage.

    upstream   : where data comes FROM (job name, repo, table, etc.)
    downstream : where data goes TO
    note       : any extra context to surface in the report
    """
    upstream: list[str] = field(default_factory=list)
    downstream: list[str] = field(default_factory=list)
    note: str = ""


def resolve_lineage(
    extract: SnowflakeUsageExtract,
    resolver_fn: Callable[[SnowflakeObjectUsage], LineageInfo],
) -> SnowflakeUsageExtract:
    """
    Apply your custom lineage resolver to every usage in the extract.

    Usage:
        def my_resolver(usage: SnowflakeObjectUsage) -> LineageInfo:
            if usage.table == "FEATURE_ACCOUNT_METRICS":
                return LineageInfo(
                    upstream=["aip-feature-store/load_account_features.yml"],
                    downstream=["shared-models/register_account_model.yml"],
                )
            return LineageInfo()

        resolved = resolve_lineage(extract, my_resolver)

    The resolved extract is then passed to format_as_markdown() or directly
    to compute_edp_extract() for the EDP agent.
    """
    for usage in extract.usages:
        try:
            info = resolver_fn(usage)
            usage.upstream = info.upstream
            usage.downstream = info.downstream
            usage.lineage_note = info.note
        except Exception:
            pass
    return extract


def format_as_markdown(extract: SnowflakeUsageExtract) -> str:
    """Return a lineage table for all Snowflake objects touched in the diff.

    DDL operations (CREATE/DROP/ALTER) are always shown — even when the snapshot
    has no upstream/downstream for them (e.g. newly created tables).
    DML operations (READ/WRITE) are only shown when the snapshot resolved lineage.
    """
    if not extract.usages:
        return ""

    # Deduplicate by object reference — merge lineage lists across multiple usages
    # of the same object (e.g. same table appears as both READ and WRITE).
    merged: dict[str, SnowflakeObjectUsage] = {}
    for u in extract.usages:
        key = u.raw_ref.upper()
        if key not in merged:
            merged[key] = u
        else:
            existing = merged[key]
            existing.upstream = list(dict.fromkeys(existing.upstream + u.upstream))
            existing.downstream = list(dict.fromkeys(existing.downstream + u.downstream))
            # Prefer DDL operation label if one exists
            if u.operation in ("CREATE", "DROP", "ALTER"):
                existing.operation = u.operation

    _DDL_OPS = {"CREATE", "DROP", "ALTER"}

    def _should_include(u: SnowflakeObjectUsage) -> bool:
        # Always include DDL — these are structural changes regardless of snapshot
        if u.operation in _DDL_OPS:
            return True
        # DML only shown when snapshot resolved upstream/downstream
        return bool(u.upstream or u.downstream)

    rows = [u for u in merged.values() if _should_include(u)]
    if not rows:
        return ""

    def _fmt_nodes(nodes: list[str], limit: int = 5) -> str:
        truncated = nodes[:limit]
        suffix = f" (+{len(nodes) - limit} more)" if len(nodes) > limit else ""
        return ", ".join(f"`{n}`" for n in truncated) + suffix

    lines = [
        "## Snowflake Object Lineage\n",
        "| Object | Operation | Upstream | Downstream |",
        "|---|---|---|---|",
    ]

    for u in rows:
        upstream_str  = _fmt_nodes(u.upstream)  if u.upstream  else "—"
        downstream_str = _fmt_nodes(u.downstream) if u.downstream else "—"
        lines.append(f"| `{u.raw_ref}` | {u.operation} | {upstream_str} | {downstream_str} |")

    return "\n".join(lines)
