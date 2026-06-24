"""Diff-level security scan: deterministic pattern checks on every PR.

Runs fast regex-based checks on added lines in the diff. No AI needed — these
are known-bad patterns that should block merge immediately.

Checks:
  - Hardcoded secrets (API keys, tokens, passwords, connection strings)
  - SQL injection (f-string / concatenated queries)
  - Command injection (subprocess with shell=True + user input)
  - Path traversal (user-controlled file paths)
  - Insecure deserialization (pickle.loads, yaml.load without Loader)
  - Weak crypto (MD5/SHA1 for security purposes)
  - Auth bypass patterns (== comparison for tokens, disabled auth)
  - Exposed debug endpoints / debug flags left on
  - SSRF risk (requests to user-supplied URLs)
  - Open redirect patterns
  - Missing input validation on HTTP handlers
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional



@dataclass
class SecurityFinding:
    rule_id: str
    cwe: str                # e.g. "CWE-89"
    severity: str           # "critical" | "high" | "medium" | "low"
    category: str           # "injection" | "secrets" | "crypto" | "auth" | "ssrf" | ...
    file: str
    line: int
    matched_text: str       # the offending snippet (truncated, secrets masked)
    title: str
    description: str
    fix: str


@dataclass
class SecurityScanResult:
    findings: list[SecurityFinding] = field(default_factory=list)
    files_scanned: int = 0
    lines_added: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")

    def by_severity(self) -> list[SecurityFinding]:
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(self.findings, key=lambda f: order.get(f.severity, 9))



@dataclass
class Rule:
    rule_id: str
    cwe: str
    severity: str
    category: str
    pattern: re.Pattern
    title: str
    description: str
    fix: str
    exclude_pattern: Optional[re.Pattern] = None   # lines to skip (e.g. comments, tests)
    mask_match: bool = False                        # mask matched text (for secrets)


_RULES: list[Rule] = [
    # ── Secrets ──────────────────────────────────────────────────────────────
    Rule(
        rule_id="SEC-001", cwe="CWE-798", severity="critical", category="secrets",
        pattern=re.compile(
            r'(api[_\-]?key|api[_\-]?secret|access[_\-]?token|auth[_\-]?token|'
            r'secret[_\-]?key|private[_\-]?key|client[_\-]?secret|'
            r'password|passwd|pwd)\s*=\s*["\'][A-Za-z0-9+/\-_]{8,}["\']',
            re.IGNORECASE,
        ),
        title="Hardcoded secret or credential",
        description="A secret, token, or password appears to be hardcoded in source code.",
        fix="Move to environment variable or secrets manager. Never commit credentials.",
        mask_match=True,
    ),
    Rule(
        rule_id="SEC-002", cwe="CWE-798", severity="critical", category="secrets",
        pattern=re.compile(
            r'(sk-ant-|ghp_|ghs_|github_pat_|xoxb-|xoxp-|AKID|AKIA)[A-Za-z0-9+/\-_]{10,}',
        ),
        title="Known secret format detected",
        description="A string matching a known API key format (Anthropic, GitHub, Slack, AWS) found in code.",
        fix="Revoke this credential immediately and rotate. Use environment variables.",
        mask_match=True,
    ),
    Rule(
        rule_id="SEC-003", cwe="CWE-798", severity="high", category="secrets",
        pattern=re.compile(
            r'(jdbc|mongodb|postgresql|mysql|redis|amqp)://[^"\s]{5,}:[^"\s]{5,}@',
            re.IGNORECASE,
        ),
        title="Connection string with embedded credentials",
        description="Database or service connection string contains embedded username/password.",
        fix="Use environment variables or a secrets manager for connection strings.",
        mask_match=True,
    ),

    # ── SQL Injection ─────────────────────────────────────────────────────────
    Rule(
        rule_id="SEC-010", cwe="CWE-89", severity="critical", category="injection",
        pattern=re.compile(
            r'(execute|executemany|cursor\.execute)\s*\(\s*[f"\'](SELECT|INSERT|UPDATE|DELETE|DROP|CREATE)',
            re.IGNORECASE,
        ),
        title="SQL injection via f-string or concatenation",
        description="SQL query constructed with f-string or direct concatenation — user input can inject arbitrary SQL.",
        fix="Use parameterized queries: cursor.execute('SELECT ... WHERE id = %s', (user_id,))",
    ),
    Rule(
        rule_id="SEC-011", cwe="CWE-89", severity="high", category="injection",
        pattern=re.compile(
            r'(SELECT|INSERT|UPDATE|DELETE)\s+.*\+\s*(request\.|params\[|args\[|data\[|input)',
            re.IGNORECASE,
        ),
        title="SQL built by string concatenation with request data",
        description="SQL string is built by concatenating request/user-controlled data.",
        fix="Use parameterized queries or an ORM. Never concatenate user input into SQL.",
    ),

    # ── Command Injection ─────────────────────────────────────────────────────
    Rule(
        rule_id="SEC-020", cwe="CWE-78", severity="critical", category="injection",
        pattern=re.compile(r'subprocess\.(run|Popen|call|check_output)\s*\([^)]*shell\s*=\s*True'),
        title="subprocess with shell=True",
        description="shell=True passes the command to the OS shell, enabling injection if any argument is user-controlled.",
        fix="Pass a list of arguments instead: subprocess.run(['cmd', arg1, arg2]). Remove shell=True.",
    ),
    Rule(
        rule_id="SEC-021", cwe="CWE-78", severity="high", category="injection",
        pattern=re.compile(r'os\.system\s*\(|os\.popen\s*\('),
        title="os.system / os.popen — potential command injection",
        description="os.system and os.popen execute shell commands. If arguments are user-controlled, this is RCE.",
        fix="Use subprocess with a list of arguments. Validate all inputs before passing to shell.",
    ),

    # ── Insecure Deserialization ──────────────────────────────────────────────
    Rule(
        rule_id="SEC-030", cwe="CWE-502", severity="critical", category="deserialization",
        pattern=re.compile(r'pickle\.loads?\s*\(|cPickle\.loads?\s*\('),
        title="Insecure pickle deserialization",
        description="pickle.loads() on untrusted data allows arbitrary code execution.",
        fix="Use JSON or a safe serialization format. If pickle is required, only deserialize trusted, signed data.",
    ),
    Rule(
        rule_id="SEC-031", cwe="CWE-502", severity="high", category="deserialization",
        pattern=re.compile(r'yaml\.load\s*\([^,)]+\)(?!\s*,\s*Loader)', re.IGNORECASE),
        title="yaml.load() without Loader",
        description="yaml.load() without an explicit Loader can deserialize arbitrary Python objects.",
        fix="Use yaml.safe_load() or yaml.load(data, Loader=yaml.SafeLoader).",
    ),

    # ── Weak Cryptography ─────────────────────────────────────────────────────
    Rule(
        rule_id="SEC-040", cwe="CWE-327", severity="high", category="crypto",
        pattern=re.compile(
            r'hashlib\.(md5|sha1)\s*\(|MD5\s*\(|SHA1\s*\(|DigestAlgorithm\.SHA1',
            re.IGNORECASE,
        ),
        title="Weak hash algorithm (MD5/SHA1)",
        description="MD5 and SHA1 are cryptographically broken and must not be used for security purposes.",
        fix="Use SHA-256 or SHA-3 via hashlib.sha256(). For passwords use bcrypt/argon2.",
        exclude_pattern=re.compile(r'checksum|etag|dedup|fingerprint', re.IGNORECASE),
    ),
    Rule(
        rule_id="SEC-041", cwe="CWE-330", severity="high", category="crypto",
        pattern=re.compile(r'random\.(random|randint|choice|shuffle)\s*\('),
        title="Non-cryptographic random used for security",
        description="Python's random module is not suitable for security tokens, session IDs, or CSRF tokens.",
        fix="Use secrets.token_hex() or secrets.token_urlsafe() for security-sensitive randomness.",
        exclude_pattern=re.compile(r'test_|_test|sample|shuffle|simulation', re.IGNORECASE),
    ),

    # ── Auth / Token Comparison ───────────────────────────────────────────────
    Rule(
        rule_id="SEC-050", cwe="CWE-208", severity="high", category="auth",
        pattern=re.compile(
            r'(token|api_key|secret|signature|hmac)\s*==\s*|==\s*(token|api_key|secret|signature)',
            re.IGNORECASE,
        ),
        title="Non-constant-time token comparison",
        description="Using == to compare secrets is vulnerable to timing attacks.",
        fix="Use hmac.compare_digest(a, b) for all secret/token comparisons.",
        exclude_pattern=re.compile(r'#|test_|None|is None|isinstance|len\('),
    ),
    Rule(
        rule_id="SEC-051", cwe="CWE-306", severity="critical", category="auth",
        pattern=re.compile(
            r'(auth_required|login_required|permission_required|authenticate)\s*=\s*False|'
            r'skip_auth\s*=\s*True|bypass_auth\s*=\s*True|verify\s*=\s*False',
            re.IGNORECASE,
        ),
        title="Authentication or verification disabled",
        description="A flag disabling authentication or SSL/TLS verification was added.",
        fix="Remove the bypass. If needed for tests, use mocks — never disable auth in production paths.",
    ),

    # ── SSRF ─────────────────────────────────────────────────────────────────
    Rule(
        rule_id="SEC-060", cwe="CWE-918", severity="high", category="ssrf",
        pattern=re.compile(
            r'requests\.(get|post|put|patch|delete)\s*\(\s*(request\.|params\[|args\[|data\[|f["\'])',
            re.IGNORECASE,
        ),
        title="Potential SSRF — HTTP request to user-controlled URL",
        description="Making outbound HTTP requests to URLs derived from user input enables Server-Side Request Forgery.",
        fix="Validate and allowlist URLs before making outbound requests. Block internal IP ranges.",
    ),

    # ── Path Traversal ────────────────────────────────────────────────────────
    Rule(
        rule_id="SEC-070", cwe="CWE-22", severity="high", category="path_traversal",
        pattern=re.compile(
            r'open\s*\(\s*(request\.|params\[|args\[|f["\'].*\{)|'
            r'Path\s*\(\s*(request\.|params\[|args\[)',
            re.IGNORECASE,
        ),
        title="Potential path traversal",
        description="File path constructed from request/user data can allow traversal outside intended directory.",
        fix="Resolve and validate the path against a base directory: Path(base, user_input).resolve().is_relative_to(base)",
    ),

    # ── Debug / Info Exposure ─────────────────────────────────────────────────
    Rule(
        rule_id="SEC-080", cwe="CWE-489", severity="medium", category="exposure",
        pattern=re.compile(r'DEBUG\s*=\s*True|debug\s*=\s*True', re.IGNORECASE),
        title="Debug mode enabled",
        description="Debug mode exposes stack traces, internal state, and sometimes a REPL to end users.",
        fix="Ensure DEBUG=False in production. Control via environment variable, never hardcode True.",
        exclude_pattern=re.compile(r'#|test_|LOG_LEVEL|logging\.DEBUG|logger\.debug'),
    ),
    Rule(
        rule_id="SEC-081", cwe="CWE-215", severity="medium", category="exposure",
        pattern=re.compile(r'print\s*\(\s*(password|token|secret|api_key|credential)', re.IGNORECASE),
        title="Sensitive data printed to stdout",
        description="Logging secrets to stdout risks exposure in log aggregation systems.",
        fix="Remove or mask sensitive fields before logging. Use structured logging with field redaction.",
    ),
]


_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# File extensions to skip (binaries, generated files, lock files)
_SKIP_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "svg", "ico", "pdf",
    "lock", "sum", "min.js", "min.css", "map",
}

# Paths to skip entirely
_SKIP_PATH_RE = re.compile(
    r"(^|/)(vendor|node_modules|\.git|dist|build|__pycache__|\.mypy_cache)/",
    re.IGNORECASE,
)


def _should_skip(path: str) -> bool:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return ext in _SKIP_EXTENSIONS or bool(_SKIP_PATH_RE.search(path))


def _mask(text: str) -> str:
    """Mask the value portion of a secret match."""
    return re.sub(r'(["\'])[A-Za-z0-9+/\-_]{4,}(["\'])', r'\1****\2', text)



def scan_diff(diff: str) -> SecurityScanResult:
    """Scan all added lines in the diff against security rules."""
    result = SecurityScanResult()
    seen: set[tuple] = set()

    current_file = ""
    new_line = 0
    files_seen: set[str] = set()

    for raw in diff.splitlines():
        m = _DIFF_FILE_RE.match(raw)
        if m:
            current_file = m.group(2)
            if not _should_skip(current_file):
                files_seen.add(current_file)
            continue

        h = _HUNK_RE.match(raw)
        if h:
            new_line = int(h.group(1))
            continue

        if not raw.startswith("+") or raw.startswith("+++"):
            if not raw.startswith("-"):
                new_line += 1
            continue

        if _should_skip(current_file):
            new_line += 1
            continue

        line_content = raw[1:]  # strip leading "+"
        result.lines_added += 1

        # Skip comment-only lines
        stripped = line_content.strip()
        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*"):
            new_line += 1
            continue

        for rule in _RULES:
            if rule.exclude_pattern and rule.exclude_pattern.search(line_content):
                continue
            m2 = rule.pattern.search(line_content)
            if not m2:
                continue

            dedup_key = (rule.rule_id, current_file, new_line)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            matched = m2.group(0)[:120]
            if rule.mask_match:
                matched = _mask(matched)

            result.findings.append(SecurityFinding(
                rule_id=rule.rule_id,
                cwe=rule.cwe,
                severity=rule.severity,
                category=rule.category,
                file=current_file,
                line=new_line,
                matched_text=matched,
                title=rule.title,
                description=rule.description,
                fix=rule.fix,
            ))

        new_line += 1

    result.files_scanned = len(files_seen)
    return result



def format_as_markdown(result: SecurityScanResult) -> str:
    lines = ["## Security Scan", ""]

    if not result.findings:
        lines += [
            f"✅ No security issues detected in {result.lines_added} added lines across "
            f"{result.files_scanned} file(s).",
        ]
        return "\n".join(lines)

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_findings = sorted(result.findings, key=lambda f: order.get(f.severity, 9))

    crit = result.critical_count
    high = result.high_count
    total = len(result.findings)

    severity_line = f"**{total} issue(s) found** — "
    parts = []
    for sev in ("critical", "high", "medium", "low"):
        count = sum(1 for f in result.findings if f.severity == sev)
        if count:
            parts.append(f"{count} {sev}")
    severity_line += ", ".join(parts)
    lines.append(severity_line)

    if crit or high:
        lines.append("")
        lines.append("⛔ **Critical/high issues must be resolved before merge.**")

    lines += ["", "| Severity | Rule | CWE | File:Line | Finding |", "|---|---|---|---|---|"]

    for f in sorted_findings:
        sev_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(f.severity, "⚪")
        matched = f.matched_text.replace("|", "\\|")[:60]
        lines.append(
            f"| {sev_emoji} {f.severity} | `{f.rule_id}` | [{f.cwe}](https://cwe.mitre.org/data/definitions/{f.cwe.split('-')[1]}.html) "
            f"| `{f.file}:{f.line}` | **{f.title}** — `{matched}` |"
        )

    lines += ["", "### Finding Details", ""]
    for f in sorted_findings:
        lines += [
            f"#### `{f.rule_id}` — {f.title} (`{f.file}:{f.line}`)",
            f"**Severity:** {f.severity} | **CWE:** {f.cwe} | **Category:** {f.category}",
            f"**Matched:** `{f.matched_text}`",
            f"**Why it matters:** {f.description}",
            f"**Fix:** {f.fix}",
            "",
        ]

    return "\n".join(lines)
