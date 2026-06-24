"""Schema impact analysis: detect schema changes in a diff and find downstream consumers.

Detects changes to:
  - SQL DDL (ALTER TABLE, CREATE TABLE, DROP TABLE — raw .sql / .ddl files)
  - Alembic migrations (op.add_column, op.drop_column, op.alter_column, op.rename_table)
  - SQLAlchemy ORM models (Column(...), mapped_column(...), relationship changes)
  - Django ORM models (models.CharField, models.ForeignKey, etc.)
  - Pydantic models / dataclasses / TypedDict fields
  - Snowflake / BigQuery DDL patterns (VARIANT, ARRAY, STRUCT types)

For each changed schema element, scans the fetched file contents for all usages
(queries, ORM references, serializers, API handlers) and reports what will break.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field



@dataclass
class SchemaChange:
    kind: str
    # kinds: "sql_column" | "sql_table" | "alembic_column" | "alembic_table" |
    #        "sqlalchemy_column" | "django_field" | "pydantic_field" |
    #        "typeddict_field" | "dataclass_field"
    name: str          # column/field/table name
    parent: str        # table or class name
    change_type: str   # "added" | "removed" | "renamed" | "type_changed" | "modified"
    file: str
    line: int
    detail: str        # human-readable description
    col_type: str = "" # e.g. "VARCHAR(255)", "Integer", "models.CharField"


@dataclass
class SchemaConsumer:
    file: str
    line: int
    snippet: str
    consumer_kind: str = ""  # "query" | "orm" | "serializer" | "handler" | "test" | ""


@dataclass
class SchemaImpactResult:
    changes: list[SchemaChange] = field(default_factory=list)
    consumers: dict[str, list[SchemaConsumer]] = field(default_factory=dict)
    files_analyzed: int = 0


_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _parse_diff_lines(diff: str) -> list[tuple[str, str, int, str]]:
    """Return (file_path, change_type, line_no, line_content) for each +/- line."""
    results = []
    current_file = ""
    new_line = 0
    old_line = 0

    for raw in diff.splitlines():
        m = _DIFF_FILE_RE.match(raw)
        if m:
            current_file = m.group(2)
            continue
        h = _HUNK_RE.match(raw)
        if h:
            new_line = int(h.group(1))
            old_line = new_line
            continue
        if not current_file:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            results.append((current_file, "added", new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            results.append((current_file, "removed", old_line, raw[1:]))
        else:
            new_line += 1
            old_line += 1

    return results


# ── Raw SQL DDL ──────────────────────────────────────────────────────────────
_SQL_ALTER_RE = re.compile(
    r"ALTER\s+TABLE\s+[`\"']?([\w.]+)[`\"']?\s+"
    r"(ADD|DROP|MODIFY|CHANGE|RENAME)\s+(?:COLUMN\s+)?[`\"']?(\w+)[`\"']?",
    re.IGNORECASE,
)
_SQL_CREATE_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TRANSIENT\s+|VOLATILE\s+|TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?([\w.]+)[`\"']?",
    re.IGNORECASE,
)
_SQL_DROP_TABLE_RE = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?[`\"']?([\w.]+)[`\"']?", re.IGNORECASE)
_SQL_COL_RE = re.compile(
    r"^\s+[`\"']?(\w+)[`\"']?\s+"
    r"(INT|BIGINT|SMALLINT|TINYINT|INTEGER|SERIAL|BIGSERIAL|"
    r"VARCHAR|NVARCHAR|CHAR|TEXT|CLOB|"
    r"BOOLEAN|BOOL|"
    r"FLOAT|DOUBLE|REAL|NUMERIC|DECIMAL|NUMBER|MONEY|"
    r"DATE|DATETIME|TIMESTAMP|TIME|INTERVAL|"
    r"JSON|JSONB|BLOB|BYTEA|BINARY|VARBINARY|"
    r"UUID|OID|"
    r"VARIANT|ARRAY|STRUCT|GEOGRAPHY|GEOMETRY)"  # Snowflake / BigQuery types
    r"\b",
    re.IGNORECASE,
)
_SQL_RESERVED = {
    "PRIMARY", "UNIQUE", "KEY", "INDEX", "CONSTRAINT", "CHECK", "FOREIGN",
    "REFERENCES", "DEFAULT", "NOT", "NULL", "AUTO_INCREMENT", "IDENTITY",
}

# ── Alembic migrations ────────────────────────────────────────────────────────
_ALEMBIC_ADD_COL_RE = re.compile(
    r"op\.add_column\s*\(\s*['\"](\w+)['\"].*?sa\.Column\s*\(\s*['\"](\w+)['\"].*?([\w()]+)",
    re.IGNORECASE | re.DOTALL,
)
_ALEMBIC_DROP_COL_RE = re.compile(
    r"op\.drop_column\s*\(\s*['\"](\w+)['\"],\s*['\"](\w+)['\"]",
    re.IGNORECASE,
)
_ALEMBIC_ALTER_COL_RE = re.compile(
    r"op\.alter_column\s*\(\s*['\"](\w+)['\"],\s*['\"](\w+)['\"]",
    re.IGNORECASE,
)
_ALEMBIC_RENAME_TABLE_RE = re.compile(
    r"op\.rename_table\s*\(\s*['\"](\w+)['\"],\s*['\"](\w+)['\"]",
    re.IGNORECASE,
)
_ALEMBIC_CREATE_TABLE_RE = re.compile(
    r"op\.create_table\s*\(\s*['\"](\w+)['\"]",
    re.IGNORECASE,
)
_ALEMBIC_DROP_TABLE_RE = re.compile(
    r"op\.drop_table\s*\(\s*['\"](\w+)['\"]",
    re.IGNORECASE,
)

# ── SQLAlchemy ORM ────────────────────────────────────────────────────────────
# Matches: col_name = Column(String(50), ...) or col_name: Mapped[str] = mapped_column(...)
_SA_COLUMN_RE = re.compile(
    r"^\s+(\w+)\s*(?::\s*Mapped\[[\w\[\], |]+\])?\s*=\s*(?:mapped_column|Column)\s*\((.{0,80})\)",
    re.IGNORECASE,
)
_SA_TABLENAME_RE = re.compile(r"__tablename__\s*=\s*['\"](\w+)['\"]")
_SA_RELATIONSHIP_RE = re.compile(
    r"^\s+(\w+)\s*=\s*relationship\s*\(\s*['\"](\w+)['\"]",
)

# SQLAlchemy base classes
_SA_BASES = {"Base", "DeclarativeBase", "DeclarativeMeta", "db.Model", "Model"}

# ── Django ORM ────────────────────────────────────────────────────────────────
_DJANGO_FIELD_RE = re.compile(
    r"^\s{4}(\w+)\s*=\s*models\.([\w]+Field|ForeignKey|ManyToManyField|OneToOneField|"
    r"GenericForeignKey|GenericRelation)\s*\(",
)
_DJANGO_MODEL_BASE_RE = re.compile(r"^class\s+(\w+)\s*\(.*models\.Model.*\)")

# ── Python class detection ────────────────────────────────────────────────────
_CLASS_RE = re.compile(r"^class\s+(\w+)\s*\(([^)]*)\)")
_DATACLASS_DECO_RE = re.compile(r"@dataclasses?\.dataclass|@dataclass")
_PYDANTIC_FIELD_RE = re.compile(r"^\s{4}(\w+)\s*:\s*[\w\[\], |]+(?:\s*=\s*Field\()?")
_TYPEDDICT_KEY_RE = re.compile(r"^\s{4}(\w+)\s*:\s*[\w\[\], |]+$")
_DATACLASS_FIELD_RE = re.compile(
    r"^\s{4}(\w+)\s*:\s*[\w\[\], |]+(?:\s*=\s*(?:field\(|dataclasses\.field\())?",
)

_PYDANTIC_BASES = {"BaseModel", "BaseSettings", "SQLModel", "BaseSchema"}
_TYPEDDICT_BASES = {"TypedDict"}


def _looks_like_sql(line: str) -> bool:
    kw = ("ALTER TABLE", "CREATE TABLE", "DROP TABLE", "INSERT INTO", "UPDATE ", "SELECT ")
    return any(line.upper().startswith(k) for k in kw)


def _is_alembic_file(path: str) -> bool:
    return "migration" in path.lower() or "alembic" in path.lower() or "versions" in path.lower()


def _is_django_models_file(path: str) -> bool:
    return "models" in path.lower() and path.endswith(".py")


def _is_sqlalchemy_file(path: str, content_snippet: str) -> bool:
    return "Column" in content_snippet or "mapped_column" in content_snippet or "__tablename__" in content_snippet



def _detect_schema_changes(diff_lines: list[tuple[str, str, int, str]]) -> list[SchemaChange]:
    changes: list[SchemaChange] = []

    by_file: dict[str, list[tuple[str, int, str]]] = {}
    for file, ctype, lineno, content in diff_lines:
        by_file.setdefault(file, []).append((ctype, lineno, content))

    for file, lines in by_file.items():
        ext = file.rsplit(".", 1)[-1].lower()
        is_sql = ext in ("sql", "ddl")
        is_py = ext == "py"
        is_alembic = _is_alembic_file(file)

        current_table = ""
        current_class = ""
        current_class_kind = ""  # "pydantic"|"typeddict"|"dataclass"|"sqlalchemy"|"django"|""
        sa_tablename = ""
        in_create = False

        for ctype, lineno, content in lines:
            stripped = content.strip()

            # ── Raw SQL ───────────────────────────────────────────────────────
            if is_sql or _looks_like_sql(stripped):
                m = _SQL_ALTER_RE.search(content)
                if m:
                    table, op, col = m.group(1), m.group(2).lower(), m.group(3)
                    op_map = {"add": "added", "drop": "removed", "modify": "type_changed",
                              "change": "renamed", "rename": "renamed"}
                    changes.append(SchemaChange(
                        kind="sql_column", name=col, parent=table,
                        change_type=op_map.get(op, "modified"), file=file, line=lineno,
                        detail=f"SQL ALTER TABLE — {op.upper()} COLUMN `{col}` on `{table}`",
                    ))
                    continue

                m = _SQL_DROP_TABLE_RE.search(content)
                if m:
                    changes.append(SchemaChange(
                        kind="sql_table", name=m.group(1), parent="",
                        change_type="removed", file=file, line=lineno,
                        detail=f"SQL DROP TABLE `{m.group(1)}`",
                    ))
                    continue

                m = _SQL_CREATE_RE.search(content)
                if m:
                    current_table = m.group(1)
                    in_create = True
                    if ctype == "added":
                        changes.append(SchemaChange(
                            kind="sql_table", name=current_table, parent="",
                            change_type="added", file=file, line=lineno,
                            detail=f"New SQL table `{current_table}`",
                        ))
                    continue

                if in_create:
                    mc = _SQL_COL_RE.match(content)
                    if mc:
                        col = mc.group(1)
                        if col.upper() not in _SQL_RESERVED:
                            changes.append(SchemaChange(
                                kind="sql_column", name=col, parent=current_table,
                                change_type=ctype, file=file, line=lineno,
                                col_type=mc.group(2),
                                detail=f"SQL column `{col}` ({mc.group(2)}) {ctype} in `{current_table}`",
                            ))
                    if stripped.startswith(")") or stripped == ");":
                        in_create = False
                continue  # SQL lines handled

            # ── Alembic migrations ────────────────────────────────────────────
            if is_alembic and is_py:
                m = _ALEMBIC_ADD_COL_RE.search(content)
                if m:
                    table, col, col_type = m.group(1), m.group(2), m.group(3)
                    changes.append(SchemaChange(
                        kind="alembic_column", name=col, parent=table,
                        change_type="added", file=file, line=lineno, col_type=col_type,
                        detail=f"Alembic op.add_column — `{col}` ({col_type}) added to `{table}`",
                    ))
                    continue

                m = _ALEMBIC_DROP_COL_RE.search(content)
                if m:
                    table, col = m.group(1), m.group(2)
                    changes.append(SchemaChange(
                        kind="alembic_column", name=col, parent=table,
                        change_type="removed", file=file, line=lineno,
                        detail=f"Alembic op.drop_column — `{col}` removed from `{table}`",
                    ))
                    continue

                m = _ALEMBIC_ALTER_COL_RE.search(content)
                if m:
                    table, col = m.group(1), m.group(2)
                    changes.append(SchemaChange(
                        kind="alembic_column", name=col, parent=table,
                        change_type="type_changed", file=file, line=lineno,
                        detail=f"Alembic op.alter_column — `{col}` altered in `{table}`",
                    ))
                    continue

                m = _ALEMBIC_RENAME_TABLE_RE.search(content)
                if m:
                    old, new = m.group(1), m.group(2)
                    changes.append(SchemaChange(
                        kind="alembic_table", name=old, parent="",
                        change_type="renamed", file=file, line=lineno,
                        detail=f"Alembic op.rename_table — `{old}` → `{new}`",
                    ))
                    continue

                m = _ALEMBIC_CREATE_TABLE_RE.search(content)
                if m:
                    changes.append(SchemaChange(
                        kind="alembic_table", name=m.group(1), parent="",
                        change_type="added", file=file, line=lineno,
                        detail=f"Alembic op.create_table — `{m.group(1)}`",
                    ))
                    continue

                m = _ALEMBIC_DROP_TABLE_RE.search(content)
                if m:
                    changes.append(SchemaChange(
                        kind="alembic_table", name=m.group(1), parent="",
                        change_type="removed", file=file, line=lineno,
                        detail=f"Alembic op.drop_table — `{m.group(1)}`",
                    ))
                    continue

            # ── Python ORM / model files ──────────────────────────────────────
            if not is_py:
                continue

            # Track class context
            m = _CLASS_RE.match(stripped)
            if m:
                cls_name, bases = m.group(1), m.group(2)
                base_list = [b.strip() for b in bases.split(",")]
                if any(b in _PYDANTIC_BASES for b in base_list):
                    current_class, current_class_kind = cls_name, "pydantic"
                elif any(b in _TYPEDDICT_BASES for b in base_list):
                    current_class, current_class_kind = cls_name, "typeddict"
                elif any(b in _SA_BASES or "Base" in b for b in base_list):
                    current_class, current_class_kind = cls_name, "sqlalchemy"
                elif _DJANGO_MODEL_BASE_RE.match(stripped):
                    current_class, current_class_kind = cls_name, "django"
                else:
                    current_class, current_class_kind = cls_name, ""
                continue

            if _DATACLASS_DECO_RE.match(stripped):
                current_class_kind = "dataclass"
                continue

            # SQLAlchemy __tablename__
            m = _SA_TABLENAME_RE.search(content)
            if m:
                sa_tablename = m.group(1)
                continue

            # SQLAlchemy Column / mapped_column
            if current_class_kind == "sqlalchemy" and ctype in ("added", "removed"):
                m = _SA_COLUMN_RE.match(content)
                if m:
                    col_name = m.group(1)
                    col_args = m.group(2)[:60]
                    table_ref = sa_tablename or current_class
                    changes.append(SchemaChange(
                        kind="sqlalchemy_column", name=col_name, parent=table_ref,
                        change_type=ctype, file=file, line=lineno, col_type=col_args,
                        detail=f"SQLAlchemy Column `{col_name}` ({col_args}) {ctype} in `{current_class}` (table: `{table_ref}`)",
                    ))
                    continue

                m = _SA_RELATIONSHIP_RE.match(content)
                if m:
                    rel_name, target = m.group(1), m.group(2)
                    changes.append(SchemaChange(
                        kind="sqlalchemy_column", name=rel_name, parent=current_class,
                        change_type=ctype, file=file, line=lineno,
                        detail=f"SQLAlchemy relationship `{rel_name}` → `{target}` {ctype} in `{current_class}`",
                    ))
                    continue

            # Django fields
            if current_class_kind == "django" and ctype in ("added", "removed"):
                m = _DJANGO_FIELD_RE.match(content)
                if m:
                    field_name, field_type = m.group(1), m.group(2)
                    changes.append(SchemaChange(
                        kind="django_field", name=field_name, parent=current_class,
                        change_type=ctype, file=file, line=lineno, col_type=field_type,
                        detail=f"Django `models.{field_type}` field `{field_name}` {ctype} in `{current_class}`",
                    ))
                    continue

            # Pydantic
            if current_class_kind == "pydantic" and ctype in ("added", "removed"):
                m = _PYDANTIC_FIELD_RE.match(content)
                if m and not stripped.startswith(("#", "def ", "class ", "model_config")):
                    fname = m.group(1)
                    if fname not in ("class", "def"):
                        changes.append(SchemaChange(
                            kind="pydantic_field", name=fname, parent=current_class,
                            change_type=ctype, file=file, line=lineno,
                            detail=f"Pydantic field `{fname}` {ctype} in `{current_class}`",
                        ))

            # TypedDict
            elif current_class_kind == "typeddict" and ctype in ("added", "removed"):
                m = _TYPEDDICT_KEY_RE.match(content)
                if m and not stripped.startswith(("#", "def ")):
                    fname = m.group(1)
                    if fname not in ("class", "def"):
                        changes.append(SchemaChange(
                            kind="typeddict_field", name=fname, parent=current_class,
                            change_type=ctype, file=file, line=lineno,
                            detail=f"TypedDict key `{fname}` {ctype} in `{current_class}`",
                        ))

            # Dataclass
            elif current_class_kind == "dataclass" and ctype in ("added", "removed"):
                m = _DATACLASS_FIELD_RE.match(content)
                if m and not stripped.startswith(("#", "def ")):
                    fname = m.group(1)
                    if fname not in ("class", "def"):
                        changes.append(SchemaChange(
                            kind="dataclass_field", name=fname, parent=current_class,
                            change_type=ctype, file=file, line=lineno,
                            detail=f"Dataclass field `{fname}` {ctype} in `{current_class}`",
                        ))

            # Reset class context on unindented non-decorator line
            if content and not content[0].isspace() and not stripped.startswith("@"):
                if not _CLASS_RE.match(stripped):
                    current_class_kind = ""

    return changes


# Patterns that indicate how a name is being *used* (not just mentioned)
_QUERY_USE_RE = re.compile(r"(SELECT|INSERT|UPDATE|DELETE|WHERE|JOIN|SET)\b", re.IGNORECASE)
_ORM_USE_RE = re.compile(r"\.(filter|filter_by|order_by|group_by|annotate|values|only|defer)\s*\(")
_SERIALIZER_RE = re.compile(r"(Serializer|Schema|Validator|Form)\s*\(")
_HANDLER_RE = re.compile(r"(request|response|payload|body|data)\[")
_TEST_USE_RE = re.compile(r"(assert|assertEqual|assertEqual|expect|test_)", re.IGNORECASE)


def _consumer_kind(snippet: str) -> str:
    if _QUERY_USE_RE.search(snippet):
        return "query"
    if _ORM_USE_RE.search(snippet):
        return "orm"
    if _SERIALIZER_RE.search(snippet):
        return "serializer"
    if _HANDLER_RE.search(snippet):
        return "handler"
    if _TEST_USE_RE.search(snippet):
        return "test"
    return ""


def _find_consumers(name: str, file_contents: dict[str, str]) -> list[SchemaConsumer]:
    pattern = re.compile(r'\b' + re.escape(name) + r'\b')
    consumers = []
    for path, content in file_contents.items():
        for lineno, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                snippet = line.strip()[:120]
                consumers.append(SchemaConsumer(
                    file=path, line=lineno, snippet=snippet,
                    consumer_kind=_consumer_kind(snippet),
                ))
    return consumers



def compute_schema_impact(diff: str, file_contents: dict[str, str]) -> SchemaImpactResult:
    diff_lines = _parse_diff_lines(diff)
    changes = _detect_schema_changes(diff_lines)

    # Deduplicate
    seen: set[tuple] = set()
    unique: list[SchemaChange] = []
    for c in changes:
        key = (c.kind, c.name, c.parent, c.change_type)
        if key not in seen:
            seen.add(key)
            unique.append(c)

    result = SchemaImpactResult(changes=unique, files_analyzed=len(file_contents))

    for change in unique:
        consumers = _find_consumers(change.name, file_contents)
        # Exclude the defining file
        consumers = [c for c in consumers if c.file != change.file]
        if consumers:
            key = f"{change.parent}.{change.name}" if change.parent else change.name
            result.consumers[key] = consumers

    return result


_KIND_LABEL = {
    "sql_column": "SQL DDL column",
    "sql_table": "SQL DDL table",
    "alembic_column": "Alembic column",
    "alembic_table": "Alembic table",
    "sqlalchemy_column": "SQLAlchemy ORM",
    "django_field": "Django ORM",
    "pydantic_field": "Pydantic field",
    "typeddict_field": "TypedDict key",
    "dataclass_field": "Dataclass field",
}

_CONSUMER_EMOJI = {
    "query": "🗄️", "orm": "🔗", "serializer": "📋",
    "handler": "🌐", "test": "🧪", "": "📄",
}


def format_as_markdown(result: SchemaImpactResult) -> str:
    if not result.changes:
        return (
            "## Schema Impact Analysis\n\n"
            "_No schema changes detected (SQL DDL, Alembic, SQLAlchemy, Django ORM, "
            "Pydantic, TypedDict, dataclasses)._\n"
        )

    lines = [
        "## Schema Impact Analysis",
        "",
        f"_Detected **{len(result.changes)} schema change(s)** across {result.files_analyzed} file(s). "
        "Covers: SQL DDL · Alembic migrations · SQLAlchemy · Django ORM · Pydantic · TypedDict · Dataclasses._",
        "",
        "### Changed Schema Elements",
        "",
        "| Element | Kind | Type | Parent | Change | File:Line |",
        "|---|---|---|---|---|---|",
    ]

    for c in result.changes:
        kind_label = _KIND_LABEL.get(c.kind, c.kind)
        parent = f"`{c.parent}`" if c.parent else "—"
        col_type = f"`{c.col_type}`" if c.col_type else "—"
        lines.append(
            f"| `{c.name}` | {kind_label} | {col_type} | {parent} | **{c.change_type}** | `{c.file}:{c.line}` |"
        )

    lines.append("")

    if result.consumers:
        lines += ["### Downstream Consumers", ""]
        lines.append(
            "_Icons: 🗄️ raw query · 🔗 ORM · 📋 serializer · 🌐 API handler · 🧪 test · 📄 other_"
        )
        lines.append("")
        for key, consumers in sorted(result.consumers.items()):
            lines.append(f"**`{key}`** — {len(consumers)} reference(s):")
            for c in consumers[:12]:
                emoji = _CONSUMER_EMOJI.get(c.consumer_kind, "📄")
                snippet = c.snippet.replace("|", "\\|")
                lines.append(f"  - {emoji} `{c.file}:{c.line}` — `{snippet}`")
            if len(consumers) > 12:
                lines.append(f"  - _…and {len(consumers) - 12} more_")
            lines.append("")
        lines.append(
            "⚠️ **Review checklist:** every consumer above may break. "
            "Removed/renamed elements cause runtime errors; type changes cause silent data corruption."
        )
    else:
        lines += [
            "### Downstream Consumers",
            "",
            "_No references found in the fetched files. The changed schema elements may be "
            "consumed outside this PR context — treat as potentially breaking._",
        ]

    return "\n".join(lines)
