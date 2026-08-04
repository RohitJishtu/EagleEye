"""Build synthesis input bundle for repo evaluation."""

from __future__ import annotations

from ...core.models import ModuleReadResult, RepoMap
from ...features.repo_auditor import AuditResult
from .redact import redact_text

DEFAULT_LLM_EXCLUDE_PREFIXES = ("data/", "out/", "fixtures/", "tests/")


def _path_excluded(path: str, include_data_dirs: bool) -> bool:
    if include_data_dirs:
        return False
    lower = path.lower()
    return any(lower.startswith(p) for p in DEFAULT_LLM_EXCLUDE_PREFIXES)


def filter_llm_file_contents(
    contents: dict[str, str],
    include_data_dirs: bool = False,
) -> dict[str, str]:
    return {
        path: content
        for path, content in contents.items()
        if not _path_excluded(path, include_data_dirs)
    }


def format_audit_markdown(audit: AuditResult) -> str:
    if not audit.findings:
        return "No deterministic audit findings."
    lines = [f"**{audit.summary()}**\n"]
    for f in audit.findings[:40]:
        loc = f"`{f.file}`" + (f" line {f.line}" if f.line else "")
        lines.append(f"- [{f.severity.upper()}] {f.title} — {loc}: {f.description[:200]}")
    if len(audit.findings) > 40:
        lines.append(f"- ... and {len(audit.findings) - 40} more")
    return "\n".join(lines)


def build_module_bundle(
    module_name: str,
    file_contents: dict[str, str],
    max_chars_per_file: int = 12000,
) -> str:
    """User payload for a single-module deep-read LLM call."""
    files_text = "\n\n".join(
        f"### {path}\n```\n{redact_text(content[:max_chars_per_file])}\n```"
        for path, content in sorted(file_contents.items())
    )
    tree_slice = "\n".join(f"  {p}" for p in sorted(file_contents.keys()))
    return (
        f"## Module\n`{module_name}`\n\n"
        f"## Files in this deep-read\n\n{tree_slice or '(none)'}\n\n"
        f"## File contents\n\n{files_text or '(none)'}\n"
    )


def format_module_reads_markdown(module_reads: list[ModuleReadResult]) -> str:
    if not module_reads:
        return "(No module deep-reads available.)"
    blocks: list[str] = []
    for m in module_reads:
        blocks.append(
            f"### Module `{m.module}`\n"
            f"**Purpose:** {m.purpose}\n"
            f"**Entry points:** {', '.join(m.entry_points) or 'n/a'}\n"
            f"**Key abstractions:** {', '.join(m.key_abstractions) or 'n/a'}\n"
            f"**Data flow:** {m.data_flow}\n"
            f"**Data stores:** {', '.join(m.data_stores) or 'n/a'}\n"
            f"**Integrations:** {', '.join(m.integrations) or 'n/a'}\n"
            f"**Security notes:** {'; '.join(m.security_notes) or 'none'}\n"
            f"**Gotchas:** {'; '.join(m.gotchas) or 'none'}\n"
            f"**Files read:** {', '.join(m.files_read) or 'n/a'}\n"
        )
    return "\n".join(blocks)


def build_synthesis_bundle(
    repo_map: RepoMap,
    readme: str,
    audit: AuditResult,
    key_file_contents: dict[str, str],
    coverage: dict,
    scoped_path: str | None,
    include_data_dirs: bool = False,
) -> str:
    safe_files = filter_llm_file_contents(key_file_contents, include_data_dirs)
    key_files_text = "\n\n".join(
        f"### {path}\n```\n{redact_text(content[:4000])}\n```"
        for path, content in safe_files.items()
    )

    scope_note = f"Scoped to subdirectory: `{scoped_path}`\n\n" if scoped_path else ""
    excluded = list(DEFAULT_LLM_EXCLUDE_PREFIXES) if not include_data_dirs else []

    return (
        f"{scope_note}"
        f"## Repository\n"
        f"**{repo_map.owner}/{repo_map.repo}** @ `{repo_map.branch}`\n"
        f"Description: {repo_map.description}\n"
        f"Language: {repo_map.primary_language}\n"
        f"Signals: {', '.join(repo_map.signals) or 'none'}\n"
        f"Top-level dirs: {', '.join(repo_map.top_level_dirs) or 'none'}\n\n"
        f"## Coverage\n"
        f"Tree files: {coverage.get('tree_files', 0)}\n"
        f"Audit eligible: {coverage.get('audit_eligible', 0)}\n"
        f"Audit scanned: {coverage.get('audit_scanned', 0)}\n"
        f"LLM excluded prefixes: {', '.join(excluded) or 'none'}\n\n"
        f"## README\n\n{redact_text(readme[:3000]) or '(none)'}\n\n"
        f"## File tree (sample)\n\n{repo_map.file_tree_excerpt}\n\n"
        f"## Deterministic audit findings\n\n{format_audit_markdown(audit)}\n\n"
        f"## Key file excerpts\n\n{key_files_text or '(none)'}"
    )


def build_synthesis_bundle_from_modules(
    repo_map: RepoMap,
    readme: str,
    audit: AuditResult,
    module_reads: list[ModuleReadResult],
    coverage: dict,
    scoped_path: str | None,
    include_data_dirs: bool = False,
) -> str:
    scope_note = f"Scoped to subdirectory: `{scoped_path}`\n\n" if scoped_path else ""
    excluded = list(DEFAULT_LLM_EXCLUDE_PREFIXES) if not include_data_dirs else []

    return (
        f"{scope_note}"
        f"## Repository\n"
        f"**{repo_map.owner}/{repo_map.repo}** @ `{repo_map.branch}`\n"
        f"Description: {repo_map.description}\n"
        f"Language: {repo_map.primary_language}\n"
        f"Signals: {', '.join(repo_map.signals) or 'none'}\n"
        f"Top-level dirs: {', '.join(repo_map.top_level_dirs) or 'none'}\n\n"
        f"## Coverage\n"
        f"Tree files: {coverage.get('tree_files', 0)}\n"
        f"Audit eligible: {coverage.get('audit_eligible', 0)}\n"
        f"Audit scanned: {coverage.get('audit_scanned', 0)}\n"
        f"Modules planned: {coverage.get('modules_planned', 0)}\n"
        f"Modules read: {coverage.get('modules_read', 0)}\n"
        f"Files deep-read: {coverage.get('files_deep_read', 0)}\n"
        f"LLM excluded prefixes: {', '.join(excluded) or 'none'}\n\n"
        f"## README\n\n{redact_text(readme[:3000]) or '(none)'}\n\n"
        f"## File tree (sample)\n\n{repo_map.file_tree_excerpt}\n\n"
        f"## Deterministic audit findings\n\n{format_audit_markdown(audit)}\n\n"
        f"## Module deep-reads\n\n{format_module_reads_markdown(module_reads)}\n"
    )
