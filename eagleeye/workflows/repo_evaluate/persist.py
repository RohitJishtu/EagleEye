"""Persist repo evaluation reports to markdown."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from ...core.models import RepoEvaluationResult
from ...core.paths import evaluations_dir
from ...workflows.review.persist import slugify_title


def _format_findings_section(title: str, findings: list) -> str:
    if not findings:
        return f"## {title}\n\nNone identified.\n\n"
    lines = [f"## {title}\n"]
    for f in findings:
        loc = f"`{f.file}`" + (f" (line {f.line})" if f.line else "")
        lines.append(f"### [{f.severity.upper()}] {f.title}")
        lines.append(f"**Location:** {loc} | **Source:** {f.source}")
        lines.append(f"\n{f.description}\n")
        lines.append(f"**Fix:** {f.fix}\n")
    return "\n".join(lines) + "\n"


def format_evaluation_markdown(result: RepoEvaluationResult) -> str:
    r = result.ratings
    body = (
        f"# Repo Evaluation: {result.repo}\n\n"
        f"**Risk:** {result.risk_level.upper()} | "
        f"**Overall grade:** {r.overall_grade} | "
        f"**Security:** {r.security_grade} | "
        f"Secrets: {r.secrets_status} | PII: {r.pii_status}\n\n"
        f"## Executive summary\n\n{result.executive_summary}\n\n"
        f"## What this repo is\n\n{result.what_it_is}\n\n"
        f"## Problem solved\n\n{result.problem_solved}\n\n"
        f"## How it works\n\n{result.how_it_works}\n\n"
        + _format_findings_section("Critical vulnerabilities", result.critical_vulnerabilities)
        + _format_findings_section("Secrets & PII risks", result.secrets_and_pii_risks)
        + f"## Future scope (stated by author)\n\n{result.future_scope_stated or '_None stated in README/docs._'}\n\n"
        f"## Future scope (inferred)\n\n{result.future_scope_inferred or '_N/A_'}\n\n"
        f"## Recommendations\n\n"
        + "".join(f"- {rec}\n" for rec in result.recommendations)
        + "\n"
    )
    if r.rating_notes:
        body += "**Rating notes:**\n" + "".join(f"- {n}\n" for n in r.rating_notes) + "\n"
    if result.confidence_notes:
        body += "**Confidence notes:**\n" + "".join(f"- {n}\n" for n in result.confidence_notes) + "\n"
    cov = result.coverage
    if cov:
        body += (
            f"\n## Coverage\n\n"
            f"- Tree files: {cov.get('tree_files', '?')}\n"
            f"- Audit eligible: {cov.get('audit_eligible', '?')}\n"
            f"- Audit scanned: {cov.get('audit_scanned', '?')}\n"
        )
    if result.synthesis_failed:
        body += "\n> **Note:** LLM synthesis failed or was skipped — deterministic findings only.\n"
    return body


def save_evaluation(
    owner: str,
    repo: str,
    result: RepoEvaluationResult,
    token_usage=None,
) -> Path:
    slug = slugify_title(repo) or repo
    ts = int(time.time())
    date_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    filename = f"eval-{slug}-{ts}.md"

    out_dir = evaluations_dir(owner, repo)
    out_dir.mkdir(parents=True, exist_ok=True)

    token_fm = ""
    if token_usage is not None:
        total_in = getattr(token_usage, "total_input", 0)
        total_out = getattr(token_usage, "output_tokens", 0)
        token_fm = f"tokens_input: {total_in}\ntokens_output: {total_out}\n"

    filepath = out_dir / filename
    content = (
        f"---\n"
        f"repo: {owner}/{repo}\n"
        f"branch: {result.branch}\n"
        f"scoped_path: {result.scoped_path or ''}\n"
        f"date: {date_str}\n"
        f"timestamp_utc: {ts}\n"
        f"risk_level: {result.risk_level}\n"
        f"overall_grade: {result.ratings.overall_grade}\n"
        f"synthesis_failed: {result.synthesis_failed}\n"
        f"{token_fm}"
        f"---\n\n"
        + format_evaluation_markdown(result)
    )
    filepath.write_text(content)
    return filepath
