"""Verdict enforcement and finding deduplication for PR reviews."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ...core.models import PRReviewResult

_ISSUE_CLUSTERS: list[set[str]] = [
    {"create or replace table"},
    {"drop table"},
    {"truncate table"},
    {"breaking change", "downstream"},
    {"breaking change", "consumers"},
    {"data loss", "downstream"},
]


def _normalize_comment(text: str) -> str:
    """Strip ALL_CAPS identifiers and numbers so findings on different tables/envs collapse."""
    text = re.sub(r'\b[A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9_]*)+\b', '', text)
    text = re.sub(r'\b[A-Z][A-Z0-9_]{3,}\b', '', text)
    text = re.sub(r'\b\d+\b', 'N', text)
    return ' '.join(text.lower().split())


def _share_issue_cluster(a: str, b: str) -> bool:
    al, bl = a.lower(), b.lower()
    return any(
        all(kw in al for kw in cluster) and all(kw in bl for kw in cluster)
        for cluster in _ISSUE_CLUSTERS
    )


def _are_similar_comments(a: str, b: str) -> bool:
    if a.split()[:8] == b.split()[:8]:
        return True
    if _share_issue_cluster(a, b):
        return True
    na, nb = _normalize_comment(a), _normalize_comment(b)
    if SequenceMatcher(None, na, nb).ratio() >= 0.72:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.75


def group_similar_findings(comments: list) -> list:
    """Merge findings with same severity+category and similar text; surface extras in the suggestion."""
    result: list = []
    used: set[int] = set()

    for i, fc in enumerate(comments):
        if i in used:
            continue
        group = [fc]
        for j in range(i + 1, len(comments)):
            if j in used:
                continue
            other = comments[j]
            if fc.severity != other.severity or fc.category != other.category:
                continue
            if _are_similar_comments(fc.comment, other.comment):
                group.append(other)
                used.add(j)

        used.add(i)
        if len(group) == 1:
            result.append(fc)
            continue

        extra = [
            other.file + (f":{other.line_range}" if other.line_range else "")
            for other in group[1:]
        ]
        note = f"Also affects {len(extra)} more file(s): {', '.join(extra)}"
        new_suggestion = (fc.suggestion + " | " + note) if fc.suggestion else note
        result.append(fc.model_copy(update={"suggestion": new_suggestion}))

    return result


def enforce_verdict_rules(result: PRReviewResult) -> PRReviewResult:
    """Hard-enforce verdict + risk consistency: request_changes needs a critical; risk≥high needs critical or ≥2 highs."""
    severities = {fc.severity.lower() for fc in result.file_comments}
    has_critical = "critical" in severities
    high_count = sum(1 for fc in result.file_comments if fc.severity.lower() == "high")
    crit_count = sum(1 for fc in result.file_comments if fc.severity.lower() == "critical")

    verdict = result.overall_verdict
    risk = result.risk_level

    if verdict == "request_changes" and not has_critical:
        verdict = "comment"
    if verdict == "approve" and (has_critical or high_count >= 2):
        verdict = "comment"

    if risk == "critical" and crit_count < 2:
        risk = "high"
    if risk == "high" and not has_critical and high_count < 2:
        risk = "medium"
    if risk == "medium" and not has_critical and high_count == 0:
        risk = "low"

    if verdict != result.overall_verdict or risk != result.risk_level:
        return result.model_copy(update={"overall_verdict": verdict, "risk_level": risk})
    return result
