"""Lightweight per-repo PR history index."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

_HISTORY_DIR = Path.home() / ".eagleeye" / "history"


@dataclass
class PRHistoryEntry:
    pr_number: int
    title: str
    merged_at: str
    author: str
    files_changed: list[str]
    body_snippet: str
    verdict: Optional[str] = None       # approve | request_changes | comment
    risk_level: Optional[str] = None    # low | medium | high | critical
    summary: Optional[str] = None


def _history_path(owner: str, repo: str) -> Path:
    return _HISTORY_DIR / f"{owner}__{repo}.json"


def _load_raw(owner: str, repo: str) -> list[dict]:
    path = _history_path(owner, repo)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def load_history(owner: str, repo: str) -> list[PRHistoryEntry]:
    return [PRHistoryEntry(**e) for e in _load_raw(owner, repo)]


def add_entry(owner: str, repo: str, entry: PRHistoryEntry) -> None:
    """Add or update (by pr_number) an entry in the history index."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    raw = _load_raw(owner, repo)
    updated = False
    for i, e in enumerate(raw):
        if e["pr_number"] == entry.pr_number:
            raw[i] = asdict(entry)
            updated = True
            break
    if not updated:
        raw.append(asdict(entry))
    _history_path(owner, repo).write_text(json.dumps(raw, indent=2))


def get_relevant(owner: str, repo: str, files_changed: list[str]) -> list[PRHistoryEntry]:
    """Return past entries with file overlap, sorted most-recent first, capped at 5."""
    current = set(files_changed)
    history = load_history(owner, repo)
    matched = [e for e in history if current & set(e.files_changed)]
    matched.sort(key=lambda e: e.merged_at or "", reverse=True)
    return matched[:5]


def format_history_prompt(entries: list[PRHistoryEntry]) -> str:
    """Format matched past PRs as a markdown section for Claude."""
    if not entries:
        return ""

    _VERDICT_EMOJI = {
        "approve": "✅", "request_changes": "❌", "comment": "💬",
    }
    lines = ["## PR History — Past PRs Touching These Files\n"]

    for e in entries:
        verdict_str = ""
        if e.verdict and e.risk_level:
            emoji = _VERDICT_EMOJI.get(e.verdict, "🔍")
            verdict_str = f"  ·  {e.risk_level.upper()} {emoji}"
        date = e.merged_at[:10] if e.merged_at else ""
        lines.append(f"**PR #{e.pr_number}** — {e.title}{verdict_str}  ({date})")
        if e.summary:
            lines.append(f"  {e.summary}")
        elif e.body_snippet:
            lines.append(f"  {e.body_snippet[:150]}")
        lines.append("")

    return "\n".join(lines)
