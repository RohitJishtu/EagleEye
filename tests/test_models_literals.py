import pytest
from pydantic import ValidationError
from eagleeye.models import FileComment, PRReviewResult, AgentFinding, BugFinding


def test_file_comment_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        FileComment(file="f.py", severity="INVALID", category="bug", comment="x")


def test_file_comment_accepts_valid_severity():
    fc = FileComment(file="f.py", severity="critical", category="bug", comment="x")
    assert fc.severity == "critical"


def test_pr_review_result_rejects_invalid_verdict():
    with pytest.raises(ValidationError):
        PRReviewResult(summary="s", overall_verdict="APPROVE", risk_level="low")


def test_pr_review_result_rejects_invalid_risk():
    with pytest.raises(ValidationError):
        PRReviewResult(summary="s", overall_verdict="approve", risk_level="CRITICAL")


def test_pr_review_result_accepts_valid():
    r = PRReviewResult(summary="s", overall_verdict="approve", risk_level="low")
    assert r.overall_verdict == "approve"


def test_agent_finding_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        AgentFinding(agent="pr", file="f.py", severity="BAD", category="bug",
                     title="t", description="d")


def test_bug_finding_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        BugFinding(file="f.py", severity="INFO",  # INFO not valid for BugFinding
                   category="security", title="t", description="d", fix_suggestion="f")


# ---------------------------------------------------------------------------
# BugScanResult computed counts
# ---------------------------------------------------------------------------

from eagleeye.models import BugScanResult


def test_bug_scan_result_counts_derived_from_findings():
    f1 = BugFinding(file="a.py", severity="critical", category="security",
                    title="t", description="d", fix_suggestion="f")
    f2 = BugFinding(file="b.py", severity="high", category="security",
                    title="t", description="d", fix_suggestion="f")
    f3 = BugFinding(file="c.py", severity="critical", category="logic",
                    title="t", description="d", fix_suggestion="f")
    result = BugScanResult(scan_target="repo", findings=[f1, f2, f3], executive_summary="sum")
    assert result.critical_count == 2
    assert result.high_count == 1
    assert result.medium_count == 0
    assert result.low_count == 0


def test_bug_scan_result_counts_update_when_findings_filtered():
    f1 = BugFinding(file="a.py", severity="critical", category="security",
                    title="t", description="d", fix_suggestion="f")
    f2 = BugFinding(file="b.py", severity="high", category="security",
                    title="t", description="d", fix_suggestion="f")
    result = BugScanResult(scan_target="repo", findings=[f1, f2], executive_summary="sum")
    assert result.critical_count == 1
    result.findings = [f2]
    assert result.critical_count == 0
    assert result.high_count == 1
