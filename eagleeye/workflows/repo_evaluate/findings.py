"""Convert audit findings and compute repo ratings."""

from __future__ import annotations

import re

from ...core.models import EvalFinding, RemediationStep, RepoMap, RepoRatings
from ...features.repo_auditor import AuditResult, HealthFinding


def health_finding_to_eval(f: HealthFinding) -> EvalFinding:
    cwe = None
    m = re.search(r"CWE-\d+", f.description)
    if m:
        cwe = m.group()
    category = f.category
    if f.checker == "HardcodedSecretChecker":
        category = "secrets"
    return EvalFinding(
        file=f.file,
        line=f.line,
        severity=f.severity,  # type: ignore[arg-type]
        category=category,
        title=f.title,
        description=f.description,
        fix=f.fix,
        source="deterministic",
        cwe_id=cwe,
    )


def audit_to_eval_findings(audit: AuditResult) -> list[EvalFinding]:
    return [health_finding_to_eval(f) for f in audit.findings]


def _letter_grade(critical: int, high: int, medium: int) -> str:
    if critical > 0:
        return "F"
    if high >= 3:
        return "D"
    if high >= 1:
        return "C"
    if medium >= 3:
        return "C+"
    if medium >= 1:
        return "B"
    return "A"


def compute_ratings(
    audit: AuditResult,
    repo_map: RepoMap,
    coverage: dict,
) -> RepoRatings:
    findings = audit_to_eval_findings(audit)
    secret_hits = [
        f for f in findings
        if f.category == "secrets"
        or "secret" in f.title.lower()
        or "token" in f.title.lower()
        or "credential" in f.title.lower()
    ]

    if any(f.severity == "critical" for f in secret_hits):
        secrets_status = "fail"
    elif secret_hits:
        secrets_status = "warn"
    else:
        secrets_status = "pass"

    medium = sum(1 for f in audit.findings if f.severity == "medium")
    security_grade = _letter_grade(audit.critical_count, audit.high_count, medium)

    pii_status: str = "pass"
    notes: list[str] = []
    if "data" in repo_map.top_level_dirs or "out" in repo_map.top_level_dirs:
        pii_status = "warn"
        notes.append(
            "Repo contains data/ or out/ directories — PII may be present (excluded from LLM by default)."
        )

    doc_score = 4 if len(repo_map.readme_excerpt) > 400 else (2 if not repo_map.readme_excerpt else 3)
    test_score = 4 if "tests" in repo_map.top_level_dirs else 2
    maint_score = 4 if len(repo_map.signals) >= 2 else 3

    overall = security_grade
    if secrets_status == "fail":
        overall = "F"

    scanned = coverage.get("audit_scanned", 0)
    eligible = coverage.get("audit_eligible", 0)
    if eligible and scanned < eligible:
        notes.append(f"Audit scanned {scanned} of {eligible} eligible files — scores are partial.")

    return RepoRatings(
        overall_grade=overall,
        security_grade=security_grade,
        secrets_status=secrets_status,  # type: ignore[arg-type]
        pii_status=pii_status,  # type: ignore[arg-type]
        documentation_score=doc_score,
        testability_score=test_score,
        maintainability_score=maint_score,
        rating_notes=notes,
    )


def merge_eval_findings(
    deterministic: list[EvalFinding],
    llm_critical: list[EvalFinding],
    llm_secrets: list[EvalFinding],
) -> tuple[list[EvalFinding], list[EvalFinding]]:
    """Merge LLM findings into deterministic lists without dropping audit hits."""

    def key(f: EvalFinding) -> tuple:
        return (f.file, f.line, f.title)

    crit: dict[tuple, EvalFinding] = {
        key(f): f for f in deterministic if f.severity in ("critical", "high")
    }
    for f in llm_critical:
        crit.setdefault(key(f), f)

    sec: dict[tuple, EvalFinding] = {}
    for f in deterministic:
        if f.category in ("secrets", "pii") or "secret" in f.title.lower():
            sec[key(f)] = f
    for f in llm_secrets:
        sec.setdefault(key(f), f)

    for f in deterministic:
        if f.category == "security" and f.severity == "medium":
            crit.setdefault(key(f), f)

    return list(crit.values()), list(sec.values())


def risk_level_from_findings(critical: list[EvalFinding], audit: AuditResult) -> str:
    if audit.critical_count > 0 or any(f.severity == "critical" for f in critical):
        return "critical"
    if audit.high_count > 0 or any(f.severity == "high" for f in critical):
        return "high"
    if audit.findings:
        return "medium"
    return "low"


_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def build_remediation_plan(
    findings: list[EvalFinding],
    *,
    max_steps: int = 6,
) -> list[RemediationStep]:
    """Build a concrete code-change plan from findings (deterministic fallback)."""
    ordered = sorted(findings, key=lambda f: (_SEV_ORDER.get(f.severity, 9), f.file, f.title))
    steps: list[RemediationStep] = []
    seen: set[tuple] = set()
    for f in ordered:
        key = (f.file, f.title)
        if key in seen:
            continue
        seen.add(key)
        loc = f"`{f.file}`" + (f" line {f.line}" if f.line else "")
        steps.append(
            RemediationStep(
                priority=len(steps) + 1,
                severity=f.severity,  # type: ignore[arg-type]
                title=f.title[:80],
                files=[f.file] if f.file else [],
                problem=(f.description or f.title)[:400],
                change_plan=(
                    f.fix
                    or f"Edit {loc}: replace the unsafe pattern with a safe equivalent and add a regression test."
                ),
                acceptance_check=(
                    f"Re-run `eagleeye evaluate --no-llm` and confirm this finding is gone for {loc}."
                ),
            )
        )
        if len(steps) >= max_steps:
            break
    return steps

