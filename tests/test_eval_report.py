"""Tests for evaluation HTML report generation."""

from __future__ import annotations

from pathlib import Path

from eagleeye.presentation.html.eval_report import process


def test_eval_report_generates_html(tmp_path):
    md = tmp_path / "eval-widget-1700000000.md"
    md.write_text(
        "---\n"
        "repo: acme/widget\n"
        "branch: main\n"
        "date: 2026-07-10 12:00 UTC\n"
        "risk_level: critical\n"
        "overall_grade: F\n"
        "synthesis_failed: False\n"
        "---\n\n"
        "# Repo Evaluation: acme/widget\n\n"
        "**Risk:** CRITICAL | **Overall grade:** F | **Security:** F | Secrets: pass | PII: warn\n\n"
        "## Executive summary\n\n"
        "One critical SQL issue found.\n\n"
        "## Critical vulnerabilities\n\n"
        "### [CRITICAL] SQL injection\n"
        "**Location:** `core/ingest.py` (line 66) | **Source:** deterministic\n\n"
        "Dynamic SQL via f-string.\n\n"
        "**Fix:** Use parameterized queries.\n"
        "\n"
        "## Remediation plan\n\n"
        "### 1. [CRITICAL] Parameterize SQL in ingest\n"
        "**Files:** `core/ingest.py`\n\n"
        "**Problem:** Dynamic SQL via f-string.\n\n"
        "**Change plan:** Use cursor.execute with bound parameters; add a regression test.\n\n"
        "**Acceptance check:** Re-run eagleeye evaluate --no-llm; finding gone.\n"
    )

    html_path = process(md)

    assert html_path == md.with_suffix(".html")
    html = html_path.read_text(encoding="utf-8")
    assert "EagleEye Repo Evaluation" in html
    assert "acme/widget" in html
    assert "SQL injection" in html
    assert "parameterized queries" in html
    assert "Remediation plan" in html
    assert "Change the code" in html
    assert "Acceptance check" in html
    assert 'id="action-summary"' in html
    assert "Implement the agreed EagleEye evaluation" in html
    assert "Copy action summary" in html
    assert 'href="#hits-secrets"' in html
    assert 'href="#action-summary"' in html
    assert html.find("Remediation plan") < html.find('id="action-summary"')
