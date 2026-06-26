"""Tests for enforce_verdict_rules case-insensitivity."""
from eagleeye.features.pr_review import enforce_verdict_rules
from eagleeye.models import PRReviewResult, FileComment


def _make_result(verdict: str, risk: str, severities: list[str]) -> PRReviewResult:
    comments = [
        FileComment(file="f.py", severity=s, category="bug", comment="c")
        for s in severities
    ]
    return PRReviewResult(
        overall_verdict=verdict,
        risk_level=risk,
        file_comments=comments,
        summary="s",
    )


def test_critical_forces_request_changes():
    result = _make_result("approve", "low", ["critical"])
    enforced = enforce_verdict_rules(result)
    assert enforced.overall_verdict != "approve"


def test_multiple_high_blocks_approve():
    result = _make_result("approve", "low", ["high", "high", "high"])
    enforced = enforce_verdict_rules(result)
    assert enforced.overall_verdict != "approve"


def test_lowercase_critical_still_works():
    result = _make_result("approve", "low", ["critical"])
    enforced = enforce_verdict_rules(result)
    assert enforced.overall_verdict != "approve"


def test_no_critical_allows_approve():
    result = _make_result("approve", "low", ["medium", "low"])
    enforced = enforce_verdict_rules(result)
    assert enforced.overall_verdict == "approve"
