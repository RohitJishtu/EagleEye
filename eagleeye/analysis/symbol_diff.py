"""Structural symbol diff: compare base vs head trees to find renames,
signature changes, decorator changes, and return-type changes.

Companion to ``blast_radius.py`` — this module produces the authoritative
"what changed" list; ``blast_radius.py`` consumes it for caller analysis.

Language support: Python only (v1).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

_PY = Language(tspython.language())
_parser = Parser(_PY)


@dataclass(frozen=True)
class Signature:
    name: str
    kind: str  # "function" | "method" | "class"
    params: tuple[str, ...]
    return_type: Optional[str]
    decorators: tuple[str, ...]
    is_async: bool
    bases: tuple[str, ...]

    def to_display(self) -> str:
        deco = "".join(f"{d}\n" for d in self.decorators)
        if self.kind == "class":
            base_part = f"({', '.join(self.bases)})" if self.bases else ""
            return f"{deco}class {self.name}{base_part}"
        async_kw = "async " if self.is_async else ""
        param_part = f"({', '.join(self.params)})"
        ret_part = f" -> {self.return_type}" if self.return_type else ""
        return f"{deco}{async_kw}def {self.name}{param_part}{ret_part}"


@dataclass(frozen=True)
class Symbol:
    file: str
    line: int
    signature: Signature
    body_hash: str


@dataclass(frozen=True)
class SymbolChange:
    kind: str  # "added" | "removed" | "renamed" | "sig_changed" | "body_changed"
    old: Optional[Symbol]
    new: Optional[Symbol]
    reason: str


@dataclass
class StructuralSymbolDiff:
    changes: list[SymbolChange] = field(default_factory=list)
    files_analyzed: int = 0
    files_skipped_no_base: int = 0
    files_skipped_non_py: int = 0

    def changed_names(self) -> list[str]:
        """Distinct symbol names across all changes — used as search seed."""
        names: set[str] = set()
        for c in self.changes:
            if c.old is not None:
                names.add(c.old.signature.name)
            if c.new is not None:
                names.add(c.new.signature.name)
        return sorted(names)


# ---------------------------------------------------------------------------
# Tree-sitter helpers
# ---------------------------------------------------------------------------


def _has_class_ancestor(node: Any) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "class_definition":
            return True
        parent = parent.parent
    return False


def _decorators_for(node: Any) -> tuple[str, ...]:
    parent = node.parent
    if parent is None or parent.type != "decorated_definition":
        return ()
    decos: list[str] = []
    for child in parent.children:
        if child.type == "decorator":
            decos.append(child.text.decode().strip())
    return tuple(decos)


def _is_async(func_node: Any) -> bool:
    for child in func_node.children:
        if child.type == "async":
            return True
    return False


def _body_hash(node: Any) -> str:
    body = node.child_by_field_name("body")
    body_bytes = body.text if body is not None else b""
    return hashlib.sha1(body_bytes).hexdigest()


def _params_tuple(func_node: Any) -> tuple[str, ...]:
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:
        return ()
    out: list[str] = []
    for child in params_node.children:
        if child.is_named:
            out.append(child.text.decode().strip())
    return tuple(out)


def _return_type(func_node: Any) -> Optional[str]:
    rt = func_node.child_by_field_name("return_type")
    return rt.text.decode().strip() if rt is not None else None


def _bases_tuple(class_node: Any) -> tuple[str, ...]:
    superclasses = class_node.child_by_field_name("superclasses")
    if superclasses is None:
        return ()
    out: list[str] = []
    for child in superclasses.children:
        if child.is_named:
            out.append(child.text.decode().strip())
    return tuple(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_symbols(path: str, source: str) -> list[Symbol]:
    """Parse `source` and return all function/method/class definitions."""
    tree = _parser.parse(source.encode())
    symbols: list[Symbol] = []

    def visit(node: Any) -> None:
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                kind = "method" if _has_class_ancestor(node) else "function"
                sig = Signature(
                    name=name_node.text.decode(),
                    kind=kind,
                    params=_params_tuple(node),
                    return_type=_return_type(node),
                    decorators=_decorators_for(node),
                    is_async=_is_async(node),
                    bases=(),
                )
                symbols.append(
                    Symbol(
                        file=path,
                        line=node.start_point[0] + 1,
                        signature=sig,
                        body_hash=_body_hash(node),
                    )
                )
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                sig = Signature(
                    name=name_node.text.decode(),
                    kind="class",
                    params=(),
                    return_type=None,
                    decorators=_decorators_for(node),
                    is_async=False,
                    bases=_bases_tuple(node),
                )
                symbols.append(
                    Symbol(
                        file=path,
                        line=node.start_point[0] + 1,
                        signature=sig,
                        body_hash=_body_hash(node),
                    )
                )
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return symbols


def diff_symbols(old: list[Symbol], new: list[Symbol]) -> list[SymbolChange]:
    """Compare two symbol lists from the same file."""
    old_by_name = {s.signature.name: s for s in old}
    new_by_name = {s.signature.name: s for s in new}

    added: list[Symbol] = []
    removed: list[Symbol] = []
    other: list[SymbolChange] = []

    for name, new_sym in new_by_name.items():
        if name not in old_by_name:
            added.append(new_sym)
            continue
        old_sym = old_by_name[name]
        if old_sym.signature != new_sym.signature:
            other.append(
                SymbolChange(
                    kind="sig_changed",
                    old=old_sym,
                    new=new_sym,
                    reason="signature changed",
                )
            )
        elif old_sym.body_hash != new_sym.body_hash:
            other.append(
                SymbolChange(
                    kind="body_changed",
                    old=old_sym,
                    new=new_sym,
                    reason="body changed",
                )
            )

    for name, old_sym in old_by_name.items():
        if name not in new_by_name:
            removed.append(old_sym)

    # Pair adds and removes with matching body_hash + kind → renames
    renames: list[SymbolChange] = []
    used_added: set[int] = set()
    used_removed: set[int] = set()
    for i, r in enumerate(removed):
        for j, a in enumerate(added):
            if j in used_added:
                continue
            if r.body_hash == a.body_hash and r.signature.kind == a.signature.kind:
                renames.append(
                    SymbolChange(
                        kind="renamed",
                        old=r,
                        new=a,
                        reason=f"renamed {r.signature.name} -> {a.signature.name}",
                    )
                )
                used_added.add(j)
                used_removed.add(i)
                break

    final_added = [
        SymbolChange(kind="added", old=None, new=a, reason="new symbol")
        for j, a in enumerate(added)
        if j not in used_added
    ]
    final_removed = [
        SymbolChange(kind="removed", old=r, new=None, reason="symbol deleted")
        for i, r in enumerate(removed)
        if i not in used_removed
    ]
    return renames + final_added + final_removed + other


def compute_structural_diff(
    base_files: dict[str, str],
    head_files: dict[str, str],
) -> StructuralSymbolDiff:
    """Run extract+diff for every Python file present in either dict."""
    result = StructuralSymbolDiff()
    all_paths = set(base_files) | set(head_files)
    for path in sorted(all_paths):
        if not path.endswith(".py"):
            result.files_skipped_non_py += 1
            continue
        base_src = base_files.get(path)
        head_src = head_files.get(path)
        if base_src is None and head_src is None:
            continue
        old_syms = extract_symbols(path, base_src) if base_src else []
        new_syms = extract_symbols(path, head_src) if head_src else []
        if base_src is None:
            result.changes.extend(
                SymbolChange(kind="added", old=None, new=s, reason="new file")
                for s in new_syms
            )
        elif head_src is None:
            result.changes.extend(
                SymbolChange(kind="removed", old=s, new=None, reason="file deleted")
                for s in old_syms
            )
        else:
            result.changes.extend(diff_symbols(old_syms, new_syms))
        result.files_analyzed += 1
    return result


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------


def _hints_for(change: SymbolChange) -> list[str]:
    """Plain-English risk hints derived from the structural change."""
    hints: list[str] = []
    o, n = change.old, change.new
    if change.kind != "sig_changed" or o is None or n is None:
        return hints

    if o.signature.is_async and not n.signature.is_async:
        hints.append("Function is no longer async — callers must stop awaiting.")
    elif not o.signature.is_async and n.signature.is_async:
        hints.append("Function is now async — every caller must `await`.")

    ort, nrt = o.signature.return_type, n.signature.return_type
    if ort and nrt and ort != nrt:
        if "Optional[" in ort and "Optional[" not in nrt:
            hints.append(
                "Return type narrowed: callers checking for `None` will break."
            )
        else:
            hints.append(f"Return type changed: `{ort}` -> `{nrt}`.")
    elif ort and not nrt:
        hints.append(f"Return type removed (was `{ort}`).")
    elif not ort and nrt:
        hints.append(f"Return type added (`{nrt}`).")

    if len(o.signature.params) < len(n.signature.params):
        hints.append("New parameter added — verify default vs required.")
    elif len(o.signature.params) > len(n.signature.params):
        hints.append("Parameter removed — callers passing it will fail.")

    added_d = set(n.signature.decorators) - set(o.signature.decorators)
    removed_d = set(o.signature.decorators) - set(n.signature.decorators)
    if added_d:
        hints.append(f"Decorator(s) added: {', '.join(sorted(added_d))}.")
    if removed_d:
        hints.append(f"Decorator(s) removed: {', '.join(sorted(removed_d))}.")

    return hints


def format_as_markdown(diff: StructuralSymbolDiff) -> str:
    """Render the structural diff as a markdown block for the agent payload."""
    if not diff.changes:
        return (
            "## Structural Changes\n\n"
            f"_Analyzed {diff.files_analyzed} Python file(s) — no symbol changes detected._\n"
        )

    sections: dict[str, list[str]] = {
        "Renamed": [],
        "Signature changed": [],
        "Added": [],
        "Removed": [],
        "Body changed (signature stable)": [],
    }

    for c in diff.changes:
        if c.kind == "renamed" and c.old and c.new:
            sections["Renamed"].append(
                f"- `{c.old.file}` — `{c.old.signature.name}` → "
                f"`{c.new.signature.name}` (body unchanged) — "
                "callers must be updated to the new name."
            )
        elif c.kind == "sig_changed" and c.old and c.new:
            block = [
                f"- `{c.new.file}:{c.new.line}` — `{c.new.signature.name}`",
                f"  - **Old:** `{c.old.signature.to_display()}`",
                f"  - **New:** `{c.new.signature.to_display()}`",
            ]
            for h in _hints_for(c):
                block.append(f"  - _{h}_")
            sections["Signature changed"].append("\n".join(block))
        elif c.kind == "added" and c.new:
            sections["Added"].append(
                f"- `{c.new.file}:{c.new.line}` — `{c.new.signature.to_display()}`"
            )
        elif c.kind == "removed" and c.old:
            sections["Removed"].append(
                f"- `{c.old.file}` — `{c.old.signature.to_display()}`"
            )
        elif c.kind == "body_changed" and c.new:
            sections["Body changed (signature stable)"].append(
                f"- `{c.new.file}:{c.new.line}` — `{c.new.signature.name}`"
            )

    lines = [
        "## Structural Changes",
        "",
        f"_Tree-sitter structural diff of {diff.files_analyzed} Python file(s). "
        "This is the authoritative list of symbol changes — verify each one's "
        "callers in the Blast Radius section._",
        "",
    ]
    for heading, items in sections.items():
        if items:
            lines.append(f"### {heading}")
            lines.append("")
            lines.extend(items)
            lines.append("")
    return "\n".join(lines)
