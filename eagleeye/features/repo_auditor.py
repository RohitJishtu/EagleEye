"""Proactive repo health checks — deterministic pattern-based auditing.

Runs a set of checkers against repo file contents.
Each checker is independent, testable, and returns structured findings.
No AI needed — these are fast, reliable catches for known anti-patterns.

Checkers:
  - IntOverflowChecker       : .cast("int") near Snowflake NUMBER(38,x) schemas
  - SqlInjectionChecker      : f-string SQL construction
  - CicdDependencyChecker    : fail_on_run_failure: false on prerequisite jobs
  - HardcodedEmailChecker    : personal emails in CI/CD configs
  - SchemaDriftChecker       : mergeSchema: true left on permanently
  - HardcodedSecretChecker   : tokens/passwords/keys in code
  - MissingErrorHandlerChecker: bare except or swallowed exceptions in pipelines
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HealthFinding:
    checker: str
    file: str
    line: Optional[int]
    severity: str        # critical | high | medium | low
    category: str        # security | data_integrity | cicd | code_quality
    title: str
    description: str
    fix: str

    def as_dict(self) -> dict:
        return {
            "checker": self.checker,
            "file": self.file,
            "line": self.line,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "fix": self.fix,
        }


@dataclass
class AuditResult:
    repo: str
    files_checked: int
    findings: list[HealthFinding] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")

    def by_severity(self) -> list[HealthFinding]:
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(self.findings, key=lambda f: order.get(f.severity, 9))

    def summary(self) -> str:
        if not self.findings:
            return f"No issues found across {self.files_checked} files."
        counts = {s: 0 for s in ["critical", "high", "medium", "low"]}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        parts = [f"{v} {k}" for k, v in counts.items() if v > 0]
        return f"{len(self.findings)} issues found ({', '.join(parts)}) across {self.files_checked} files."


class BaseChecker:
    name: str = "base"

    def check(self, filepath: str, content: str) -> list[HealthFinding]:
        raise NotImplementedError

    def _finding(self, filepath, line, severity, category, title, description, fix) -> HealthFinding:
        return HealthFinding(
            checker=self.name,
            file=filepath,
            line=line,
            severity=severity,
            category=category,
            title=title,
            description=description,
            fix=fix,
        )

    def _line_number(self, content: str, match_start: int) -> int:
        return content[:match_start].count("\n") + 1


class IntOverflowChecker(BaseChecker):
    name = "IntOverflowChecker"
    # Matches .cast("int") or .cast('int') — not .cast("integer") which is less common
    _PATTERN = re.compile(r'\.cast\(["\']int["\']\)', re.IGNORECASE)
    _LARGE_FIELD_HINTS = re.compile(
        r'(rowid|row_id|id|pk|primary_key|sequence|serial|bigint|number\(38)', re.IGNORECASE
    )

    def check(self, filepath: str, content: str) -> list[HealthFinding]:
        if not filepath.endswith(".py"):
            return []
        findings = []
        for m in self._PATTERN.finditer(content):
            # Check surrounding context (100 chars) for large-range field hints
            ctx_start = max(0, m.start() - 200)
            ctx = content[ctx_start: m.end() + 200]
            if self._LARGE_FIELD_HINTS.search(ctx):
                findings.append(self._finding(
                    filepath=filepath,
                    line=self._line_number(content, m.start()),
                    severity="high",
                    category="data_integrity",
                    title="Integer overflow risk: .cast('int') on potentially large field",
                    description=(
                        f".cast('int') limits values to ~2.1B. If this field is a ROWID, sequence, "
                        f"or maps to a Snowflake NUMBER(38,0), values above 2,147,483,647 will "
                        f"silently overflow to negative numbers causing data corruption."
                    ),
                    fix="Replace .cast('int') with .cast('long') for ROWID and large numeric fields.",
                ))
        return findings


class SqlInjectionChecker(BaseChecker):
    name = "SqlInjectionChecker"
    _FSTRING_SQL = re.compile(
        r'f["\'].*?(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|MERGE|TRUNCATE|EXEC)',
        re.IGNORECASE,
    )
    _FORMAT_SQL = re.compile(
        r'["\'].*?(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\s.*?["\'].*?(%\s*[(\[]|\.[Ff]ormat\()',
        re.IGNORECASE,
    )

    def check(self, filepath: str, content: str) -> list[HealthFinding]:
        if not filepath.endswith((".py", ".sql")):
            return []
        findings = []
        for pattern in [self._FSTRING_SQL, self._FORMAT_SQL]:
            for m in pattern.finditer(content):
                findings.append(self._finding(
                    filepath=filepath,
                    line=self._line_number(content, m.start()),
                    severity="critical",
                    category="security",
                    title="SQL injection: dynamic SQL built with f-string or string formatting",
                    description=(
                        "SQL query constructed by interpolating variables directly. "
                        "If any variable comes from external input or config parameters, "
                        "an attacker can inject arbitrary SQL. (CWE-89)"
                    ),
                    fix=(
                        "Use parameterized queries or validate/whitelist identifiers "
                        "(table/column names) against a fixed allowlist before interpolation."
                    ),
                ))
        return findings


class CicdDependencyChecker(BaseChecker):
    name = "CicdDependencyChecker"
    _PATTERN = re.compile(r'fail_on_run_failure\s*:\s*false', re.IGNORECASE)

    def check(self, filepath: str, content: str) -> list[HealthFinding]:
        if not filepath.endswith((".yml", ".yaml", ".json")):
            return []
        findings = []
        for m in self._PATTERN.finditer(content):
            findings.append(self._finding(
                filepath=filepath,
                line=self._line_number(content, m.start()),
                severity="high",
                category="cicd",
                title="CI/CD: fail_on_run_failure: false may hide prerequisite job failures",
                description=(
                    "If this job is a prerequisite (creates tables, sets up infra, runs migrations), "
                    "silent failures will cascade to all downstream jobs. "
                    "They will fail with cryptic errors instead of a clear root cause."
                ),
                fix=(
                    "Set fail_on_run_failure: true for prerequisite jobs. "
                    "Reserve false only for optional/advisory jobs."
                ),
            ))
        return findings


class HardcodedEmailChecker(BaseChecker):
    name = "HardcodedEmailChecker"
    # Match email in on_failure / notifications context
    _PATTERN = re.compile(
        r'(on_failure|on_success|email_notifications)[^\n]*\n(?:[^\n]*\n){0,3}[^\n]*[\w.\-]+@[\w.\-]+\.[a-z]{2,}',
        re.IGNORECASE,
    )
    _EMAIL = re.compile(r'[\w.\-]+@[\w.\-]+\.[a-z]{2,}')

    def check(self, filepath: str, content: str) -> list[HealthFinding]:
        if not filepath.endswith((".yml", ".yaml")):
            return []
        findings = []
        for m in self._PATTERN.finditer(content):
            # Skip matches where the email is already inside a redaction placeholder
            # (e.g. [EMAIL_ADDRESS: ...] or [EMAIL_ADDRESS: <uuid>]) — these are not live addresses.
            if "[EMAIL_ADDRESS:" in m.group():
                continue
            email_m = self._EMAIL.search(m.group())
            email = email_m.group() if email_m else "unknown"
            findings.append(self._finding(
                filepath=filepath,
                line=self._line_number(content, m.start()),
                severity="medium",
                category="cicd",
                title=f"Hardcoded personal email in CI/CD notification: {email}",
                description=(
                    "Personal email in CI/CD notifications causes alert blindness when the person "
                    "leaves the team or changes roles. Alerts go unnoticed."
                ),
                fix="Replace with a team destination_id or shared distribution list.",
            ))
        return findings


class SchemaDriftChecker(BaseChecker):
    name = "SchemaDriftChecker"
    _PATTERN = re.compile(r'\.option\(["\']mergeSchema["\'],\s*["\']true["\']\)', re.IGNORECASE)

    def check(self, filepath: str, content: str) -> list[HealthFinding]:
        if not filepath.endswith(".py"):
            return []
        findings = []
        for m in self._PATTERN.finditer(content):
            findings.append(self._finding(
                filepath=filepath,
                line=self._line_number(content, m.start()),
                severity="medium",
                category="data_integrity",
                title="mergeSchema: true allows silent schema drift in streaming job",
                description=(
                    "mergeSchema: true is useful for initial schema migration but should be "
                    "removed once all environments are bootstrapped. Leaving it on permanently "
                    "allows accidental column additions to silently propagate in production."
                ),
                fix=(
                    "Remove mergeSchema: true after the schema migration is complete "
                    "and verified in all environments."
                ),
            ))
        return findings


class HardcodedSecretChecker(BaseChecker):
    name = "HardcodedSecretChecker"
    _PATTERNS = [
        (re.compile(r'(password|passwd|secret|token|api_key|apikey|auth_key)\s*=\s*["\'][^"\']{6,}["\']',
                    re.IGNORECASE), "Hardcoded credential"),
        (re.compile(r'ghp_[A-Za-z0-9]{36}'), "GitHub personal access token"),
        (re.compile(r'sk-ant-[A-Za-z0-9\-_]{20,}'), "Anthropic API key"),
        (re.compile(r'AKIA[0-9A-Z]{16}'), "AWS access key ID"),
    ]

    def check(self, filepath: str, content: str) -> list[HealthFinding]:
        if filepath.endswith((".md", ".txt", ".lock")):
            return []
        findings = []
        for pattern, label in self._PATTERNS:
            for m in pattern.finditer(content):
                findings.append(self._finding(
                    filepath=filepath,
                    line=self._line_number(content, m.start()),
                    severity="critical",
                    category="security",
                    title=f"{label} hardcoded in source file",
                    description=(
                        "Hardcoded credentials in source code are exposed to anyone with repo access "
                        "and will persist in git history even after removal. (CWE-798)"
                    ),
                    fix="Move to environment variables or a secrets manager. Rotate the credential immediately.",
                ))
        return findings


class MissingErrorHandlerChecker(BaseChecker):
    name = "MissingErrorHandlerChecker"
    _BARE_EXCEPT = re.compile(r'except\s*:', re.MULTILINE)
    _PASS_EXCEPT = re.compile(r'except[^:]*:\s*\n\s*pass', re.MULTILINE)

    def check(self, filepath: str, content: str) -> list[HealthFinding]:
        if not filepath.endswith(".py"):
            return []
        findings = []
        for pattern, title in [
            (self._BARE_EXCEPT, "Bare except clause catches all exceptions silently"),
            (self._PASS_EXCEPT, "Exception swallowed with pass — failure will be invisible"),
        ]:
            for m in pattern.finditer(content):
                findings.append(self._finding(
                    filepath=filepath,
                    line=self._line_number(content, m.start()),
                    severity="medium",
                    category="code_quality",
                    title=title,
                    description=(
                        "In data pipelines, swallowed exceptions cause silent data loss or "
                        "partial writes that are extremely hard to debug. "
                        "The pipeline appears to succeed while data is incorrect or missing."
                    ),
                    fix=(
                        "Catch specific exception types. Log the error with context. "
                        "Re-raise or fail fast so the pipeline stops and alerts fire."
                    ),
                ))
        return findings


ALL_CHECKERS: list[BaseChecker] = [
    IntOverflowChecker(),
    SqlInjectionChecker(),
    CicdDependencyChecker(),
    HardcodedEmailChecker(),
    SchemaDriftChecker(),
    HardcodedSecretChecker(),
    MissingErrorHandlerChecker(),
]


def run_audit(file_contents: dict[str, str], repo: str = "") -> AuditResult:
    """Run all checkers against a dict of {filepath: content}.

    Returns an AuditResult with all findings sorted by severity.
    """
    result = AuditResult(repo=repo, files_checked=len(file_contents))
    for filepath, content in file_contents.items():
        for checker in ALL_CHECKERS:
            try:
                findings = checker.check(filepath, content)
                result.findings.extend(findings)
            except Exception:
                pass  # never let a broken checker kill the whole audit
    result.findings = result.by_severity()
    return result
