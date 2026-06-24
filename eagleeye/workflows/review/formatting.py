"""Format PR review results as GitHub markdown comments."""

from __future__ import annotations

import re

from ...core.models import PRReviewResult

_VERDICT_LABEL = {
    "approve": "Okay to merge",
    "request_changes": "Let's revisit",
    "comment": "Needs attention",
}

_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]

_CHANGE_TYPE_LABEL = {
    "added": "Added",
    "modified": "Modified",
    "removed": "Removed",
    "schema_changed": "Schema changed",
    "config_changed": "Config changed",
}

_VERDICT_EMOJI = {"approve": "✅", "request_changes": "❌", "comment": "💬"}
_RISK_EMOJI = {"critical": "🚨", "high": "🔴", "medium": "🟡", "low": "🟢"}


def edp_downstream(details: str) -> str:
    match = re.search(r'[Dd]ownstream:\s*(.+?)$', details)
    if not match:
        return ""
    ds = match.group(1).strip().rstrip('.')
    return "" if ds.lower() in ("none known", "none", "—", "-") else ds


def _edp_tree_block(entries: list[tuple[str, str, str]], max_downstream: int = 50) -> str:
    tree_lines: list[str] = []
    for name, label, downstream_csv in entries:
        if tree_lines:
            tree_lines.append("")
        tree_lines.append(f"{name}  [{label}]")
        items = [d.strip() for d in downstream_csv.split(",") if d.strip()]
        shown = items[:max_downstream]
        extra = len(items) - max_downstream
        for i, item in enumerate(shown):
            is_last = (i == len(shown) - 1) and extra <= 0
            connector = "└── " if is_last else "├── "
            tree_lines.append(f"  {connector}{item}")
        if extra > 0:
            tree_lines.append(f"  └── (+{extra} more)")
    return "```\n" + "\n".join(tree_lines) + "\n```"


def format_comment_markdown(
    result: PRReviewResult,
    pr_url: str = "",
    pr_title: str = "",
    pr_number: int = 0,
    owner_repo: str = "",
) -> str:
    """Format a PRReviewResult as a GitHub markdown comment."""
    verdict_label = _VERDICT_LABEL.get(result.overall_verdict, result.overall_verdict)
    verdict_emoji = _VERDICT_EMOJI.get(result.overall_verdict, "🔍")
    risk_emoji = _RISK_EMOJI.get(result.risk_level, "⚪")

    if pr_number and pr_title:
        pr_ref = f"PR #{pr_number} · {pr_title}"
    else:
        pr_ref = pr_title or (f"PR #{pr_number}" if pr_number else "PR Review")
    if owner_repo:
        repo_ref = owner_repo
    elif "github.com" in pr_url:
        repo_ref = pr_url.split("github.com/")[-1].rsplit("/pull/", 1)[0]
    else:
        repo_ref = ""

    lines = [
        f"## EagleEye Code Review {verdict_emoji}",
        "",
        f"**{pr_ref}**" if pr_ref != "PR Review" else "**PR Review**",
    ]
    if result.requested_by:
        lines.append(f"Requested by: @{result.requested_by}")
    if repo_ref:
        lines.append(f"Repo: `{repo_ref}`")
    if pr_url:
        lines.append(pr_url)
    lines += [
        "",
        f"**Review:** {verdict_label} {verdict_emoji}  &nbsp;·&nbsp;  **Risk:** `{result.risk_level.upper()}` {risk_emoji}",
        "",
        "---",
        "",
        "### Summary",
        result.summary,
        "",
    ]

    high_priority = [fc for fc in result.file_comments if fc.severity in ("critical", "high", "medium")]
    sorted_hp: list = []
    if high_priority:
        def _sev_key(c):
            return _SEVERITY_ORDER.index(c.severity) if c.severity in _SEVERITY_ORDER else 99
        sorted_hp = sorted(high_priority, key=_sev_key)

        crit_count = sum(1 for fc in sorted_hp if fc.severity == "critical")
        high_count = sum(1 for fc in sorted_hp if fc.severity == "high")
        med_count = sum(1 for fc in sorted_hp if fc.severity == "medium")
        count_str = f" ({crit_count} 🚨 Critical, {high_count} 🔴 High, {med_count} 🟡 Medium)" if any([crit_count, high_count, med_count]) else ""

        lines += [f"### Findings{count_str}", ""]
        current_sev = None
        for fc in sorted_hp:
            if fc.severity != current_sev:
                current_sev = fc.severity
                lines.append(f"**{fc.severity.upper()}**")
            loc = f"`{fc.file}`"
            if fc.line_range:
                loc += f":{fc.line_range}"
            lines.append(f"- {fc.comment} — {loc}")
        lines.append("")

    if result.blocking_issues:
        lines += [f"### Blocking Issues ({len(result.blocking_issues)})", ""]
        for issue in result.blocking_issues:
            lines.append(f"- {issue}")
        lines.append("")

    if result.feature_store_impact and result.feature_store_impact.affected_features:
        fsi = result.feature_store_impact
        lines += ["### Feature Store Impact Analysis", ""]
        if fsi.summary:
            lines += [fsi.summary, ""]
        lines += ["| Feature | Change | Downstream Models | Details |", "|---|---|---|---|"]
        for af in fsi.affected_features:
            models = ", ".join(af.downstream_models) if af.downstream_models else "—"
            label = _CHANGE_TYPE_LABEL.get(af.change_type, af.change_type)
            lines.append(f"| {af.name} | {label} | {models} | {af.details} |")
        lines.append("")

    if result.edp_impact and result.edp_impact.affected_pipelines:
        edp = result.edp_impact
        entries = []
        for ap in edp.affected_pipelines:
            downstream = edp_downstream(ap.details)
            if not downstream:
                continue
            label = _CHANGE_TYPE_LABEL.get(ap.change_type, ap.change_type)
            entries.append((ap.name, label, downstream))
        if entries:
            lines += ["### EDP Impact Analysis", ""]
            if edp.summary:
                lines += [edp.summary, ""]
            lines += [_edp_tree_block(entries), ""]

    misc = [fc for fc in result.file_comments if fc.severity in ("low", "info")]
    if misc:
        lines += [f"### Misc Issues ({len(misc)})", ""]
        for fc in misc:
            loc = f"`{fc.file}`"
            if fc.line_range:
                loc += f":{fc.line_range}"
            lines.append(f"- **`{fc.severity.upper()}`** {loc} — {fc.comment}")
            if fc.suggestion:
                lines.append(f"  > 💡 {fc.suggestion}")
        lines.append("")

    if result.positive_highlights:
        lines += [f"### Positive Highlights ({len(result.positive_highlights)})", ""]
        for h in result.positive_highlights:
            lines.append(f"- {h}")
        lines.append("")

    if high_priority:
        lines += ["### Remediation Details", ""]
        for fc in sorted_hp:
            loc = f"`{fc.file}`"
            if fc.line_range:
                loc += f" (lines {fc.line_range})"
            lines += [f"**`{fc.severity.upper()}`** {loc}", fc.comment]
            if fc.suggestion:
                lines.append(f"> 💡 {fc.suggestion}")
            lines.append("")

    lines += [
        "---",
        "_Generated by EagleEye powered by Claude_",
    ]

    return "\n".join(lines)
