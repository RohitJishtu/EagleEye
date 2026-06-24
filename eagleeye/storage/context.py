"""Repo context store — save analyzed repo summaries and inject them into future reviews.

Contexts live at ~/.eagleeye/contexts/{owner}__{repo}.json
Standard (always-include) repos are flagged in ~/.eagleeye/contexts/_index.json

Usage:
  eagleeye context save owner/repo          # analyze + save
  eagleeye context list                     # show saved contexts
  eagleeye context show owner/repo          # print a saved context
  eagleeye context remove owner/repo        # delete
  eagleeye context standard owner/repo      # mark as always-include
  eagleeye context unstandard owner/repo    # remove always-include flag
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

_CONTEXTS_DIR = Path.home() / ".eagleeye" / "contexts"
_INDEX_FILE = _CONTEXTS_DIR / "_index.json"



@dataclass
class RepoContext:
    owner: str
    repo: str
    saved_at: float               # Unix timestamp
    purpose: str                  # one-line description
    tech_stack: list[str]
    architecture_summary: str
    entry_points: list[str]
    external_dependencies: list[str]
    key_tables_and_schemas: list[str]   # extracted DB/schema info
    key_apis: list[str]                  # public API surface
    file_tree_summary: str               # condensed tree (top 50 paths)
    is_standard: bool = False            # always injected into reviews



def _ensure_dir() -> None:
    _CONTEXTS_DIR.mkdir(parents=True, exist_ok=True)


def _context_path(owner: str, repo: str) -> Path:
    return _CONTEXTS_DIR / f"{owner}__{repo}.json"


def _load_index() -> dict[str, bool]:
    """Returns {owner/repo: is_standard}."""
    if not _INDEX_FILE.exists():
        return {}
    try:
        return json.loads(_INDEX_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_index(index: dict[str, bool]) -> None:
    _ensure_dir()
    _INDEX_FILE.write_text(json.dumps(index, indent=2))



def save_context(owner: str, repo: str, summary, file_tree: list[dict]) -> Path:
    """Persist a RepoSummaryResult as a context entry.

    Args:
        owner, repo: repo coordinates
        summary: RepoSummaryResult from repo_reader
        file_tree: raw file tree from GitHub
    """
    _ensure_dir()

    # Extract condensed file tree (paths only, top 60)
    paths = [item["path"] for item in file_tree if item.get("type") == "blob"][:60]
    tree_str = "\n".join(paths)

    # Extract schema/table hints from architecture layers
    schema_hints = []
    api_hints = []
    for layer in getattr(summary, "architecture_layers", []):
        name_lower = layer.name.lower()
        if any(k in name_lower for k in ("schema", "model", "database", "table", "migration", "orm")):
            schema_hints.append(f"{layer.name}: {layer.description}")
        if any(k in name_lower for k in ("api", "endpoint", "handler", "route", "service", "interface")):
            api_hints.append(f"{layer.name}: {layer.description}")

    index = _load_index()
    is_standard = index.get(f"{owner}/{repo}", False)

    ctx = RepoContext(
        owner=owner,
        repo=repo,
        saved_at=time.time(),
        purpose=getattr(summary, "purpose", ""),
        tech_stack=list(getattr(summary, "tech_stack", [])),
        architecture_summary="\n".join(
            f"  [{l.name}] {l.description}"
            for l in getattr(summary, "architecture_layers", [])
        ),
        entry_points=list(getattr(summary, "entry_points", [])),
        external_dependencies=list(getattr(summary, "external_dependencies", [])),
        key_tables_and_schemas=schema_hints,
        key_apis=api_hints,
        file_tree_summary=tree_str,
        is_standard=is_standard,
    )

    path = _context_path(owner, repo)
    path.write_text(json.dumps(asdict(ctx), indent=2))

    # Update index
    index[f"{owner}/{repo}"] = is_standard
    _save_index(index)

    return path


def load_context(owner: str, repo: str) -> Optional[RepoContext]:
    path = _context_path(owner, repo)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return RepoContext(**data)
    except (json.JSONDecodeError, TypeError, OSError):
        return None


def list_contexts() -> list[RepoContext]:
    if not _CONTEXTS_DIR.exists():
        return []
    contexts = []
    for p in sorted(_CONTEXTS_DIR.glob("*__*.json")):
        try:
            data = json.loads(p.read_text())
            contexts.append(RepoContext(**data))
        except (json.JSONDecodeError, TypeError, OSError):
            pass
    return contexts


def remove_context(owner: str, repo: str) -> bool:
    path = _context_path(owner, repo)
    if path.exists():
        path.unlink()
        index = _load_index()
        index.pop(f"{owner}/{repo}", None)
        _save_index(index)
        return True
    return False


def set_standard(owner: str, repo: str, standard: bool) -> bool:
    """Mark or unmark a repo as always-include. Returns False if context not found."""
    path = _context_path(owner, repo)
    if not path.exists():
        return False
    ctx = load_context(owner, repo)
    if ctx is None:
        return False
    ctx.is_standard = standard
    path.write_text(json.dumps(asdict(ctx), indent=2))
    index = _load_index()
    if standard:
        index[f"{owner}/{repo}"] = True
    else:
        index.pop(f"{owner}/{repo}", None)
    _save_index(index)
    return True


def get_standard_contexts() -> list[RepoContext]:
    return [c for c in list_contexts() if c.is_standard]


def get_relevant_contexts(
    file_list: list[str],
    diff: str,
    extra_repos: Optional[list[str]] = None,
) -> list[RepoContext]:
    """Return contexts relevant to the current PR/analysis.

    Includes:
    1. All standard (always-include) contexts
    2. Any explicitly requested repos (extra_repos = ["owner/repo", ...])
    3. Contexts whose repo name appears in the diff or file paths (heuristic)
    """
    all_contexts = list_contexts()
    if not all_contexts:
        return []

    selected: dict[str, RepoContext] = {}

    # Always include standard repos
    for ctx in all_contexts:
        if ctx.is_standard:
            selected[f"{ctx.owner}/{ctx.repo}"] = ctx

    # Explicitly requested
    if extra_repos:
        for repo_slug in extra_repos:
            parts = repo_slug.strip().split("/")
            if len(parts) == 2:
                ctx = load_context(parts[0], parts[1])
                if ctx:
                    selected[repo_slug] = ctx

    # Heuristic: repo name mentioned in diff or file paths
    combined_text = diff[:5000] + " ".join(file_list)
    for ctx in all_contexts:
        slug = f"{ctx.owner}/{ctx.repo}"
        if slug not in selected and (
            ctx.repo.lower() in combined_text.lower()
            or ctx.owner.lower() in combined_text.lower()
        ):
            selected[slug] = ctx

    return list(selected.values())


def format_contexts_as_prompt(contexts: list[RepoContext]) -> str:
    """Format saved contexts as a markdown section for injection into Claude prompts."""
    if not contexts:
        return ""

    lines = [
        "## Known Repository Contexts (use for cross-repo impact analysis)",
        "",
        "The following repos have been pre-analyzed. Use this knowledge to identify "
        "cross-repo dependencies, schema contracts, and API surfaces that the current "
        "change may affect.",
        "",
    ]

    for ctx in contexts:
        age_days = int((time.time() - ctx.saved_at) / 86400)
        tag = " [STANDARD]" if ctx.is_standard else ""
        lines += [
            f"### `{ctx.owner}/{ctx.repo}`{tag}",
            f"_Saved {age_days}d ago_",
            "",
            f"**Purpose:** {ctx.purpose}",
            f"**Stack:** {', '.join(ctx.tech_stack)}",
            f"**Entry points:** {', '.join(ctx.entry_points[:5]) or 'none'}",
            f"**External deps:** {', '.join(ctx.external_dependencies[:8]) or 'none'}",
            "",
        ]
        if ctx.architecture_summary:
            lines += ["**Architecture:**", "```", ctx.architecture_summary[:600], "```", ""]
        if ctx.key_tables_and_schemas:
            lines += ["**Key schemas/models:**"]
            for s in ctx.key_tables_and_schemas[:5]:
                lines.append(f"  - {s}")
            lines.append("")
        if ctx.key_apis:
            lines += ["**Key APIs:**"]
            for a in ctx.key_apis[:5]:
                lines.append(f"  - {a}")
            lines.append("")
        if ctx.file_tree_summary:
            lines += ["**File tree (top paths):**", "```", ctx.file_tree_summary[:800], "```", ""]

    return "\n".join(lines)
