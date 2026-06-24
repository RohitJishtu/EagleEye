"""Blast radius analysis: find which functions changed in a PR and who calls them.

Given the PR diff and the full contents of the changed files, this module uses
Tree-sitter to structurally identify:

- Modified symbols: functions/methods/classes whose body or signature overlaps
  with a diff hunk.
- Callers: call sites in the fetched files that reference those symbols.

Output is a markdown block that is appended to the payload sent to Claude,
making cross-file impact analysis deterministic rather than prompt-coached.

Language support: Python only (v1). Non-.py files are skipped silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor

if TYPE_CHECKING:
    from .symbol_diff import StructuralSymbolDiff

_PY = Language(tspython.language())
_parser = Parser(_PY)

# Matches a function/method definition and captures its name, params, and line range.
_FUNC_QUERY = Query(
    _PY,
    """
    (function_definition
        name: (identifier) @name
        parameters: (parameters) @params
        return_type: (_)? @return_type) @func
    """,
)

# Matches a class definition.
_CLASS_QUERY = Query(
    _PY,
    """
    (class_definition
        name: (identifier) @name) @class
    """,
)

# Matches `obj.method(...)` call expressions.
_CALL_QUERY = Query(
    _PY,
    """
    (call
        function: (attribute
            attribute: (identifier) @method)
        arguments: (argument_list)) @call
    """,
)

# Matches bare `func(...)` call expressions.
_BARE_CALL_QUERY = Query(
    _PY,
    """
    (call
        function: (identifier) @name
        arguments: (argument_list)) @call
    """,
)



@dataclass
class ChangedSymbol:
    name: str
    kind: str  # "function" | "method" | "class"
    file: str
    line: int
    signature: str


@dataclass
class Caller:
    file: str
    line: int
    snippet: str


@dataclass
class BlastRadiusResult:
    changed_symbols: list[ChangedSymbol] = field(default_factory=list)
    callers: dict[str, list[Caller]] = field(default_factory=dict)
    files_analyzed: int = 0
    files_skipped: int = 0


_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_diff_hunks(diff: str) -> dict[str, set[int]]:
    """Return {file_path: {line_numbers_touched_in_new_version}}.

    Only the "+" / context lines of each hunk are tracked, because we match
    against the new file contents.
    """
    files: dict[str, set[int]] = {}
    current_file: Optional[str] = None
    new_line = 0
    in_hunk = False

    for raw in diff.splitlines():
        m = _DIFF_FILE_RE.match(raw)
        if m:
            current_file = m.group(2)
            files.setdefault(current_file, set())
            in_hunk = False
            continue

        if current_file is None:
            continue

        h = _HUNK_RE.match(raw)
        if h:
            new_line = int(h.group(1))
            in_hunk = True
            continue

        if not in_hunk:
            continue

        if raw.startswith("+") and not raw.startswith("+++"):
            files[current_file].add(new_line)
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            pass  # deletion; no new-file line consumed
        else:
            new_line += 1

    return files



def _extract_symbols_from_file(path: str, source: str) -> list[tuple[ChangedSymbol, int, int]]:
    """Return all function and class definitions with their line ranges.

    Returns tuples of (symbol, start_line, end_line) — 1-indexed, inclusive.
    """
    tree = _parser.parse(source.encode())
    symbols: list[tuple[ChangedSymbol, int, int]] = []

    for _, caps in QueryCursor(_FUNC_QUERY).matches(tree.root_node):
        func_node = caps["func"][0]
        name = caps["name"][0].text.decode()
        params = caps["params"][0].text.decode()
        ret = caps.get("return_type", [None])[0]
        ret_str = ret.text.decode() if ret else ""
        sig = f"def {name}{params}" + (f" -> {ret_str}" if ret_str else "")
        start = func_node.start_point[0] + 1
        end = func_node.end_point[0] + 1
        # Detect methods by looking for a class ancestor.
        kind = "method" if _has_class_ancestor(func_node) else "function"
        symbols.append(
            (ChangedSymbol(name=name, kind=kind, file=path, line=start, signature=sig), start, end)
        )

    for _, caps in QueryCursor(_CLASS_QUERY).matches(tree.root_node):
        class_node = caps["class"][0]
        name = caps["name"][0].text.decode()
        start = class_node.start_point[0] + 1
        end = class_node.end_point[0] + 1
        symbols.append(
            (
                ChangedSymbol(name=name, kind="class", file=path, line=start, signature=f"class {name}"),
                start,
                end,
            )
        )

    return symbols


def _has_class_ancestor(node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "class_definition":
            return True
        parent = parent.parent
    return False



def _find_calls_in_file(path: str, source: str, target_names: set[str]) -> list[Caller]:
    tree = _parser.parse(source.encode())
    callers: list[Caller] = []
    seen: set[tuple[int, str]] = set()

    def _add(method_name: str, call_node) -> None:
        if method_name not in target_names:
            return
        line = call_node.start_point[0] + 1
        key = (line, method_name)
        if key in seen:
            return
        seen.add(key)
        snippet = call_node.text.decode().replace("\n", " ")[:100]
        callers.append(Caller(file=path, line=line, snippet=snippet))

    for _, caps in QueryCursor(_CALL_QUERY).matches(tree.root_node):
        method = caps["method"][0].text.decode()
        _add(method, caps["call"][0])

    for _, caps in QueryCursor(_BARE_CALL_QUERY).matches(tree.root_node):
        name = caps["name"][0].text.decode()
        _add(name, caps["call"][0])

    return callers



def extract_changed_symbols(diff: str, pr_file_contents: dict[str, str]) -> tuple[list[ChangedSymbol], int, int]:
    """Phase 1 — extract which symbols were modified in the diff.

    Args:
        diff: raw unified diff from GitHub.
        pr_file_contents: only the PR's own changed files (NOT cross-repo callers).

    Returns:
        (changed_symbols, files_analyzed, files_skipped)
    """
    hunks = _parse_diff_hunks(diff)
    files_analyzed = 0
    files_skipped = 0
    changed_symbols: list[ChangedSymbol] = []

    for path, content in pr_file_contents.items():
        if not path.endswith(".py"):
            files_skipped += 1
            continue
        files_analyzed += 1
        touched_lines = hunks.get(path, set())
        if not touched_lines:
            continue
        for symbol, start, end in _extract_symbols_from_file(path, content):
            if any(start <= ln <= end for ln in touched_lines):
                changed_symbols.append(symbol)

    # Deduplicate: same symbol name + file + line.
    seen: set[tuple[str, str, int]] = set()
    unique: list[ChangedSymbol] = []
    for s in changed_symbols:
        key = (s.name, s.file, s.line)
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique, files_analyzed, files_skipped


def find_callers(
    changed_symbols: list[ChangedSymbol],
    expanded_file_contents: dict[str, str],
) -> dict[str, list[Caller]]:
    """Phase 2 — search for callers of the changed symbols.

    Args:
        changed_symbols: output of extract_changed_symbols().
        expanded_file_contents: full_file_contents AFTER fetch_cross_repo_callers
            has merged external caller files in — this is what gives blast radius
            its cross-repo reach. Must be called after that node completes.

    Returns:
        {symbol_name: [Caller, ...]} deduplicated.
    """
    target_names = {s.name for s in changed_symbols}
    callers: dict[str, list[Caller]] = {}

    for path, content in expanded_file_contents.items():
        if not path.endswith(".py"):
            continue
        for caller in _find_calls_in_file(path, content, target_names):
            matched_name = _extract_called_name(caller.snippet)
            if matched_name and matched_name in target_names:
                callers.setdefault(matched_name, []).append(caller)

    return callers


def compute_blast_radius(
    diff: str,
    file_contents: dict[str, str],
    structural_diff: Optional["StructuralSymbolDiff"] = None,
) -> BlastRadiusResult:
    """Compute blast radius in two explicit phases.

    Phase 1: identify what changed.
      - If ``structural_diff`` is provided (preferred, post-2026-05-18), use its
        authoritative symbol list — catches renames, signature changes, decorator
        changes that the line-overlap path cannot see.
      - Otherwise fall back to line-overlap extraction from the raw diff.
    Phase 2: search for callers across the expanded file set.

    NOTE: for maximum cross-repo reach, call this AFTER fetch_cross_repo_callers
    has populated full_file_contents with external caller files.
    """
    result = BlastRadiusResult()
    if structural_diff is not None and structural_diff.changes:
        changed_symbols: list[ChangedSymbol] = []
        for c in structural_diff.changes:
            sym = c.new or c.old
            if sym is None:
                continue
            changed_symbols.append(
                ChangedSymbol(
                    name=sym.signature.name,
                    kind=sym.signature.kind,
                    file=sym.file,
                    line=sym.line,
                    signature=sym.signature.to_display(),
                )
            )
        result.changed_symbols = changed_symbols
        result.files_analyzed = structural_diff.files_analyzed
        result.files_skipped = structural_diff.files_skipped_non_py
    else:
        changed_symbols, analyzed, skipped = extract_changed_symbols(diff, file_contents)
        result.changed_symbols = changed_symbols
        result.files_analyzed = analyzed
        result.files_skipped = skipped
    result.callers = find_callers(result.changed_symbols, file_contents)

    # Deduplicate callers per symbol.
    for name, calls in result.callers.items():
        unique: dict[tuple[str, int], Caller] = {}
        for c in calls:
            unique[(c.file, c.line)] = c
        result.callers[name] = sorted(unique.values(), key=lambda c: (c.file, c.line))

    return result


def _extract_called_name(snippet: str) -> Optional[str]:
    """Given 'obj.method(...)' or 'func(...)', return the last identifier before '('."""
    m = re.match(r"(?:.*\.)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", snippet)
    return m.group(1) if m else None



def format_as_markdown(result: BlastRadiusResult) -> str:
    """Format the blast radius result as a markdown section for the payload."""
    if not result.changed_symbols:
        return (
            "## Blast Radius Analysis\n\n"
            f"_No Python symbol changes detected in the fetched files "
            f"({result.files_analyzed} analyzed, {result.files_skipped} skipped)._\n"
        )

    lines = [
        "## Blast Radius Analysis",
        "",
        f"_Structural analysis of {result.files_analyzed} Python file(s). "
        f"Use this to verify every caller of a changed function — do not skip._",
        "",
        "### Changed Symbols",
        "",
        "| Symbol | Kind | File:Line | Signature |",
        "|---|---|---|---|",
    ]
    for s in result.changed_symbols:
        sig = s.signature.replace("|", "\\|")
        lines.append(f"| `{s.name}` | {s.kind} | `{s.file}:{s.line}` | `{sig}` |")
    lines.append("")

    if result.callers:
        lines += ["### Callers of Changed Symbols", ""]
        for name in sorted(result.callers.keys()):
            calls = result.callers[name]
            lines.append(f"**`{name}`** — {len(calls)} caller(s):")
            for c in calls:
                snippet = c.snippet.replace("|", "\\|")
                lines.append(f"  - `{c.file}:{c.line}` — `{snippet}`")
            lines.append("")
    else:
        lines += [
            "### Callers",
            "",
            "_No callers found in the fetched files. Either this symbol is called "
            "from files not fetched in this PR context, or it is unused._",
            "",
        ]

    lines.append(
        "⚠️ **Review checklist:** for each caller above, verify the changed symbol's "
        "new signature/return type is compatible. Flag any mismatch as a blocking issue."
    )
    return "\n".join(lines)
