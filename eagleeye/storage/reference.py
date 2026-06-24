"""Reference repo index — AST-based symbol extraction across multiple repos.

Builds an inverted index using tree-sitter:
  index: {symbol_name: [Match(file, line, kind, snippet), ...]}

See docs/superpowers/specs/2026-05-18-reference-repo-redesign-design.md
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

INDEX_DIR = Path.home() / ".eagleeye" / "reference"
SCHEMA_VERSION = 2

MAX_FILES_PER_REPO = 2000
MAX_MATCHES_PER_NAME = 50
MAX_FILE_SIZE_BYTES = 1_000_000
SNIPPET_MAX_LEN = 120

SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", "target", "vendor", ".git",
})


@dataclass
class Match:
    file: str
    line: int
    kind: str
    snippet: str


@dataclass
class ReferenceIndex:
    owner: str
    repo: str
    ref: str
    built_at: str
    files_indexed: int
    index: dict[str, list[Match]] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    extractor_versions: dict[str, str] = field(default_factory=dict)


def _snippet(content: str, line_1based: int) -> str:
    """Return the source line trimmed to SNIPPET_MAX_LEN chars."""
    lines = content.splitlines()
    idx = line_1based - 1
    if idx < 0 or idx >= len(lines):
        return ""
    s = lines[idx].strip()
    return s[:SNIPPET_MAX_LEN]


import tree_sitter_python
from tree_sitter import Language, Parser

_PY_LANG = Language(tree_sitter_python.language())
_py_parser = Parser(_PY_LANG)


def _text(node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def extract_py(content: str, path: str) -> list[tuple[str, Match]]:
    """Extract Python defs, calls, and imports as (name, Match) pairs."""
    source = content.encode("utf-8", errors="replace")
    tree = _py_parser.parse(source)
    results: list[tuple[str, Match]] = []

    def visit(node):
        t = node.type
        if t == "function_definition" or t == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = _text(name_node, source)
                line = name_node.start_point[0] + 1
                results.append((name, Match(path, line, "py.def", _snippet(content, line))))
        elif t == "call":
            func = node.child_by_field_name("function")
            if func is not None:
                if func.type == "identifier":
                    name = _text(func, source)
                    line = func.start_point[0] + 1
                    results.append((name, Match(path, line, "py.call", _snippet(content, line))))
                elif func.type == "attribute":
                    attr = func.child_by_field_name("attribute")
                    if attr is not None:
                        name = _text(attr, source)
                        line = attr.start_point[0] + 1
                        results.append((name, Match(path, line, "py.call", _snippet(content, line))))
        elif t == "import_from_statement":
            for child in node.children:
                if child.type == "dotted_name" and child.prev_sibling and child.prev_sibling.type == "import":
                    name = _text(child, source)
                    line = child.start_point[0] + 1
                    results.append((name, Match(path, line, "py.import", _snippet(content, line))))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    if name_node is not None:
                        name = _text(name_node, source)
                        line = name_node.start_point[0] + 1
                        results.append((name, Match(path, line, "py.import", _snippet(content, line))))

        for c in node.children:
            visit(c)

    visit(tree.root_node)
    return results


import re
import tree_sitter_sql

_SQL_LANG = Language(tree_sitter_sql.language())
_sql_parser = Parser(_SQL_LANG)

_SQL_TABLE_RE = re.compile(
    r'\b(?:FROM|JOIN|INTO|UPDATE)\s+([\w.]+)',
    re.IGNORECASE,
)
_SQL_CREATE_RE = re.compile(
    r'\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.]+)',
    re.IGNORECASE,
)
_JINJA_BLOCK_RE = re.compile(r'\{\{[^}]*\}\}|\{%[^%]*%\}')


def _norm_sql_name(raw: str) -> str:
    return raw.strip().strip('`"[]').upper()


def _strip_jinja(content: str) -> str:
    """Replace Jinja blocks with spaces of equal length so line numbers are preserved."""
    def _spaces(m: re.Match) -> str:
        return " " * len(m.group(0))
    return _JINJA_BLOCK_RE.sub(_spaces, content)


def extract_sql(content: str, path: str) -> list[tuple[str, Match]]:
    """Extract SQL table defs and refs. Regex-primary; tree-sitter import kept for future use."""
    results: list[tuple[str, Match]] = []
    scanned = _strip_jinja(content)

    for m in _SQL_CREATE_RE.finditer(scanned):
        name = _norm_sql_name(m.group(1))
        line = scanned[:m.start()].count("\n") + 1
        results.append((name, Match(path, line, "sql.table_def", _snippet(content, line))))

    for m in _SQL_TABLE_RE.finditer(scanned):
        name = _norm_sql_name(m.group(1))
        line = scanned[:m.start()].count("\n") + 1
        results.append((name, Match(path, line, "sql.table_ref", _snippet(content, line))))

    return results


import yaml


_YAML_NAME_RE = re.compile(r"^\s*-?\s*name:\s*['\"]?([^'\"\s#]+)['\"]?\s*(?:#.*)?$")


def _yaml_line(content: str, target_name: str, seen_lines: dict) -> int:
    """Find the line in content where `name: <target_name>` appears, list-item or plain.

    Each call to the same target returns a fresh unused line so duplicate names
    (e.g. column `name: account_id` vs source `name: account_id`) are not aliased.
    """
    used = seen_lines.setdefault(target_name, set())
    for i, line in enumerate(content.splitlines(), start=1):
        if i in used:
            continue
        m = _YAML_NAME_RE.match(line)
        if m and m.group(1) == target_name:
            used.add(i)
            return i
    return 1


def extract_dbt_yml(content: str, path: str) -> list[tuple[str, Match]]:
    """Extract dbt model and source names from YAML."""
    results: list[tuple[str, Match]] = []
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return results
    if not isinstance(data, dict):
        return results

    seen_lines: dict = {}

    for model in data.get("models") or []:
        if isinstance(model, dict) and "name" in model:
            name = model["name"]
            line = _yaml_line(content, name, seen_lines)
            results.append((name, Match(path, line, "dbt.model_def", _snippet(content, line))))

    for source in data.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_name = source.get("name", "")
        for table in source.get("tables") or []:
            if isinstance(table, dict) and "name" in table:
                tname = table["name"]
                line = _yaml_line(content, tname, seen_lines)
                results.append((tname, Match(path, line, "dbt.source", _snippet(content, line))))
                if source_name:
                    qualified = f"{source_name}.{tname}"
                    results.append((qualified, Match(path, line, "dbt.source", _snippet(content, line))))

    return results


_DBT_REF_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_DBT_SOURCE_RE = re.compile(
    r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}"
)


def extract_dbt_sql(content: str, path: str) -> list[tuple[str, Match]]:
    """Extract dbt ref() and source() Jinja calls from SQL files."""
    results: list[tuple[str, Match]] = []

    for m in _DBT_REF_RE.finditer(content):
        name = m.group(1)
        line = content[:m.start()].count("\n") + 1
        results.append((name, Match(path, line, "dbt.ref", _snippet(content, line))))

    for m in _DBT_SOURCE_RE.finditer(content):
        source_name, table_name = m.group(1), m.group(2)
        line = content[:m.start()].count("\n") + 1
        results.append((table_name, Match(path, line, "dbt.source", _snippet(content, line))))
        results.append((f"{source_name}.{table_name}", Match(path, line, "dbt.source", _snippet(content, line))))

    return results


import tree_sitter_javascript
import tree_sitter_typescript

_JS_LANG = Language(tree_sitter_javascript.language())
_TS_LANG = Language(tree_sitter_typescript.language_typescript())
_TSX_LANG = Language(tree_sitter_typescript.language_tsx())
_js_parser = Parser(_JS_LANG)
_ts_parser = Parser(_TS_LANG)
_tsx_parser = Parser(_TSX_LANG)


def _walk_js_like(tree, source: bytes, content: str, path: str) -> list[tuple[str, Match]]:
    results: list[tuple[str, Match]] = []

    def visit(node, depth: int):
        t = node.type
        if t in ("function_declaration", "class_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = _text(name_node, source)
                line = name_node.start_point[0] + 1
                results.append((name, Match(path, line, "js.def", _snippet(content, line))))
        elif t == "lexical_declaration" and depth <= 2:
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node is not None and name_node.type == "identifier":
                        name = _text(name_node, source)
                        line = name_node.start_point[0] + 1
                        results.append((name, Match(path, line, "js.def", _snippet(content, line))))
        elif t == "call_expression":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "identifier":
                name = _text(func, source)
                line = func.start_point[0] + 1
                results.append((name, Match(path, line, "js.call", _snippet(content, line))))
        elif t == "import_statement":
            for desc in node.children:
                if desc.type == "import_clause":
                    for sub in desc.children:
                        if sub.type == "identifier":
                            name = _text(sub, source)
                            line = sub.start_point[0] + 1
                            results.append((name, Match(path, line, "js.import", _snippet(content, line))))
                        elif sub.type == "named_imports":
                            for spec in sub.children:
                                if spec.type == "import_specifier":
                                    nm = spec.child_by_field_name("name")
                                    if nm is not None:
                                        name = _text(nm, source)
                                        line = nm.start_point[0] + 1
                                        results.append((name, Match(path, line, "js.import", _snippet(content, line))))

        for c in node.children:
            visit(c, depth + 1)

    visit(tree.root_node, 0)
    return results


def extract_js(content: str, path: str) -> list[tuple[str, Match]]:
    source = content.encode("utf-8", errors="replace")
    tree = _js_parser.parse(source)
    return _walk_js_like(tree, source, content, path)


def extract_ts(content: str, path: str) -> list[tuple[str, Match]]:
    source = content.encode("utf-8", errors="replace")
    parser = _tsx_parser if path.endswith(".tsx") else _ts_parser
    tree = parser.parse(source)
    return _walk_js_like(tree, source, content, path)


import sys


def _path_parts(path: str) -> list[str]:
    return [p for p in path.replace("\\", "/").split("/") if p]


def _under_dirs(path: str, dirnames: set[str] | frozenset[str]) -> bool:
    return any(part in dirnames for part in _path_parts(path))


def _dispatch_extractor(path: str):
    """Return the extractor function for this path, or None to skip."""
    p = path.lower()
    if p.endswith(".py"):
        return extract_py
    if p.endswith(".sql"):
        return extract_dbt_sql if _under_dirs(path, {"models"}) else extract_sql
    if p.endswith((".yml", ".yaml")):
        return extract_dbt_yml if _under_dirs(path, {"models", "sources"}) else None
    if p.endswith((".js", ".jsx")):
        return extract_js
    if p.endswith((".ts", ".tsx")):
        return extract_ts
    return None


def save_index(index: ReferenceIndex) -> Path:
    """Persist index to ~/.eagleeye/reference/{owner}-{repo}/index.json."""
    path = INDEX_DIR / f"{index.owner}-{index.repo}" / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(index)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_index(owner: str, repo: str) -> ReferenceIndex | None:
    """Load a previously built index, or return None if not found / stale schema."""
    path = INDEX_DIR / f"{owner}-{repo}" / "index.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        print(
            f"warning: reference index for {owner}/{repo} uses old schema "
            f"v{data.get('schema_version')} (current is v{SCHEMA_VERSION}). "
            f"Run: eagleeye reference build {owner}/{repo} to rebuild.",
            file=sys.stderr,
        )
        return None
    raw_index = data.get("index") or {}
    rebuilt: dict[str, list[Match]] = {
        name: [Match(**m) for m in entries]
        for name, entries in raw_index.items()
    }
    return ReferenceIndex(
        owner=data["owner"],
        repo=data["repo"],
        ref=data.get("ref", "main"),
        built_at=data["built_at"],
        files_indexed=data.get("files_indexed", 0),
        index=rebuilt,
        schema_version=data["schema_version"],
        extractor_versions=data.get("extractor_versions", {}),
    )


def _record_versions() -> dict[str, str]:
    return {
        "py": "tree-sitter-python",
        "sql": "regex-primary",
        "dbt": "yaml+jinja-regex",
        "js": "tree-sitter-javascript",
        "ts": "tree-sitter-typescript",
    }


def build_index(owner: str, repo: str, github, ref: str = "main") -> ReferenceIndex:
    """Walk the repo tree, dispatch each file to an extractor, build inverted index."""
    tree: list[dict] = github.get_repo_tree(owner, repo)

    candidates: list[str] = []
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        size = entry.get("size") or 0
        if size > MAX_FILE_SIZE_BYTES:
            continue
        if _under_dirs(path, SKIP_DIRS):
            continue
        if _dispatch_extractor(path) is None:
            continue
        candidates.append(path)
        if len(candidates) >= MAX_FILES_PER_REPO:
            break

    index: dict[str, list[Match]] = {}
    files_indexed = 0
    files_skipped: list[tuple[str, str]] = []

    for path in candidates:
        extractor = _dispatch_extractor(path)
        if extractor is None:
            continue
        try:
            content = github.get_file_content(owner, repo, path, ref=ref)
        except Exception as exc:
            files_skipped.append((path, f"fetch: {exc}"))
            continue
        try:
            pairs = extractor(content, path)
        except Exception as exc:
            files_skipped.append((path, f"parse: {exc}"))
            continue

        files_indexed += 1
        for name, match in pairs:
            bucket = index.setdefault(name, [])
            if len(bucket) >= MAX_MATCHES_PER_NAME:
                continue
            key = (match.file, match.line, match.kind)
            if any((m.file, m.line, m.kind) == key for m in bucket):
                continue
            bucket.append(match)

    return ReferenceIndex(
        owner=owner,
        repo=repo,
        ref=ref,
        built_at=datetime.now(timezone.utc).isoformat(),
        files_indexed=files_indexed,
        index=index,
        schema_version=SCHEMA_VERSION,
        extractor_versions=_record_versions(),
    )


MAX_MATCHES_IN_MARKDOWN = 10


def search_indexes(
    indexes: list[ReferenceIndex],
    changed_symbols: set[str] | list[str],
) -> str:
    """Search loaded indexes for changed symbols. Return markdown or empty string."""
    wanted = set(changed_symbols)
    if not wanted or not indexes:
        return ""

    per_repo: list[tuple[str, dict[str, list[Match]]]] = []
    total_matches = 0
    total_symbols = 0
    for idx in indexes:
        hits = {name: idx.index[name] for name in wanted if name in idx.index}
        if not hits:
            continue
        per_repo.append((f"{idx.owner}/{idx.repo}", hits))
        total_symbols += len(hits)
        total_matches += sum(len(m) for m in hits.values())

    if not per_repo:
        return ""

    lines: list[str] = [
        f"**Reference scan:** {total_symbols} symbol(s) matched across "
        f"{len(per_repo)} repo(s) ({total_matches} total matches).",
        "",
    ]

    for repo_id, hits in per_repo:
        lines.append(f"## Reference matches in `{repo_id}`")
        lines.append("")
        for name, matches in hits.items():
            shown = matches[:MAX_MATCHES_IN_MARKDOWN]
            extra = len(matches) - len(shown)
            count = len(matches)
            label = "match" if count == 1 else "matches"
            lines.append(f"### `{name}` ({count} {label})")
            for m in shown:
                lines.append(f"- `{m.file}:{m.line}` — `{m.kind}` — `{m.snippet}`")
            if extra > 0:
                lines.append(f"- _…and {extra} more_")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


_DEFINITION_KINDS: frozenset[str] = frozenset({
    "py.def", "sql.table_def", "dbt.model_def", "js.def",
})


def extract_changed_symbols(file_contents: dict[str, str]) -> set[str]:
    """Return the set of symbol names defined in the given PR files.

    Only definitions (def, class, CREATE TABLE, dbt model_def, js def) are returned.
    Call sites and imports are intentionally excluded.
    """
    symbols: set[str] = set()
    for path, content in file_contents.items():
        extractor = _dispatch_extractor(path)
        if extractor is None:
            continue
        try:
            pairs = extractor(content, path)
        except Exception:
            continue
        for name, match in pairs:
            if match.kind in _DEFINITION_KINDS:
                symbols.add(name)
    return symbols
