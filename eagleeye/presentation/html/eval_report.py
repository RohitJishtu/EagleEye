"""Convert EagleEye repo evaluation markdown to styled HTML."""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

from .report import _CSS, _RISK_BORDER, _fmt, _parse_frontmatter

_NARRATIVE_SECTIONS = (
    "Executive summary",
    "What this repo is",
    "Problem solved",
    "How it works",
    "Future scope (stated by author)",
    "Future scope (inferred)",
    "Coverage",
)


def _parse_h2_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_body: list[str] = []
    in_fence = False

    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^## (.+)$", line):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_body).strip()
            current_heading = re.match(r"^## (.+)$", line).group(1).strip()
            current_body = []
        else:
            current_body.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_body).strip()
    return sections


def _parse_eval_findings(text: str) -> list[dict]:
    findings: list[dict] = []
    blocks = re.split(r"(?=^### \[)", text, flags=re.MULTILINE)
    for block in blocks:
        block = block.strip()
        if not block.startswith("### ["):
            continue
        hm = re.match(r"^### \[([A-Z]+)\]\s*(.+)$", block, re.MULTILINE)
        if not hm:
            continue
        severity = hm.group(1)
        title = hm.group(2).split("\n", 1)[0].strip()
        rest = block[hm.end():].strip()

        location = ""
        loc_m = re.search(r"\*\*Location:\*\*\s*(.+?)(?:\n|$)", rest)
        if loc_m:
            location = loc_m.group(1).strip()
            rest = rest[loc_m.end():].strip()

        fix = ""
        fix_m = re.search(r"\*\*Fix:\*\*\s*(.+?)(?:\n\n|\Z)", rest, re.DOTALL)
        if fix_m:
            fix = fix_m.group(1).strip()
            description = rest[: fix_m.start()].strip()
        else:
            description = rest

        findings.append({
            "severity": severity,
            "title": title,
            "location": location,
            "description": description,
            "fix": fix,
        })
    return findings


def _finding_card(finding: dict) -> str:
    sev = finding["severity"].lower()
    title = _fmt(finding["title"])
    location = _fmt(finding["location"]) if finding["location"] else ""
    description = _fmt(finding["description"])
    fix_html = ""
    if finding["fix"]:
        fix_html = (
            f'<details class="fc-tip">'
            f'<summary>Recommended fix</summary>'
            f'<div class="fc-tip-text">{_fmt(finding["fix"])}</div>'
            f"</details>"
        )
    loc_html = f'<span class="fc-file">{location}</span>' if location else ""
    return f"""
<div class="finding-card sev-{sev}">
  <div class="fc-header">
    <span class="badge badge-{sev}">{finding['severity']}</span>
    {loc_html}
  </div>
  <div class="fc-desc"><strong>{title}</strong><br>{description}</div>
  {fix_html}
</div>"""


def _bullet_section(title: str, text: str) -> str:
    items = [line.strip()[2:] for line in text.splitlines() if line.strip().startswith("- ")]
    if not items:
        body = f'<div class="card">{_fmt(text) or "None identified."}</div>'
    else:
        lis = "".join(f"<li>{_fmt(item)}</li>" for item in items)
        body = f'<div class="card"><ul style="margin:0;padding-left:18px">{lis}</ul></div>'
    return f"""
  <section>
    <div class="section-title">{_html.escape(title)}</div>
    {body}
  </section>"""


def _build_eval_html(fm: dict, risk: str, sections: dict, body_text: str) -> str:
    repo = fm.get("repo", "")
    branch = fm.get("branch", "main")
    date = fm.get("date", "")
    overall = fm.get("overall_grade", "")
    synthesis_failed = fm.get("synthesis_failed", "False").lower() == "true"

    border = _RISK_BORDER.get(risk, "#b3ff47")
    risk_cls = risk.lower()
    repo_url = f"https://github.com/{repo}"

    grade_m = re.search(
        r"\*\*Risk:\*\*\s*([A-Z]+)\s*\|\s*\*\*Overall grade:\*\*\s*(\S+)",
        body_text,
    )
    security = secrets = pii = ""
    if grade_m:
        meta_m = re.search(
            r"\*\*Security:\*\*\s*(\S+)\s*\|\s*Secrets:\s*(\S+)\s*\|\s*PII:\s*(\S+)",
            body_text,
        )
        if meta_m:
            security, secrets, pii = meta_m.group(1), meta_m.group(2), meta_m.group(3)

    meta = [
        f'<span class="badge badge-{risk_cls}">{risk} RISK</span>',
        f'<span><strong>Branch:</strong> {branch}</span>',
    ]
    if overall:
        meta.append(f"<span><strong>Overall:</strong> {overall}</span>")
    if security:
        meta.append(f"<span><strong>Security:</strong> {security}</span>")
    if secrets:
        meta.append(f"<span><strong>Secrets:</strong> {secrets}</span>")
    if pii:
        meta.append(f"<span><strong>PII:</strong> {pii}</span>")
    if date:
        meta.append(f"<span><strong>Evaluated:</strong> {date}</span>")
    if synthesis_failed:
        meta.append('<span style="color:var(--muted)">Deterministic-only run</span>')

    hero = f"""
  <div class="hero" style="border:1.5px solid {border}">
    <div class="hero-top">
      <div>
        <div class="hero-eyebrow">EagleEye Repo Evaluation</div>
        <h1>{_html.escape(repo)}</h1>
      </div>
      <a href="{repo_url}" target="_blank" class="pr-link">View on GitHub &#8599;</a>
    </div>
    <div class="meta-row">{"".join(meta)}</div>
  </div>"""

    parts = [hero]
    for title in _NARRATIVE_SECTIONS:
        if title in sections and sections[title].strip():
            parts.append(f"""
  <section>
    <div class="section-title">{_html.escape(title)}</div>
    <div class="card">{_fmt(sections[title])}</div>
  </section>""")

    for findings_title in ("Critical vulnerabilities", "Secrets & PII risks"):
        if findings_title not in sections:
            continue
        findings = _parse_eval_findings(sections[findings_title])
        if findings:
            cards = "".join(_finding_card(f) for f in findings)
            body = cards
        else:
            body = f'<div class="card">{_fmt(sections[findings_title]) or "None identified."}</div>'
        parts.append(f"""
  <section>
    <div class="section-title">{_html.escape(findings_title)}</div>
    {body}
  </section>""")

    if "Recommendations" in sections:
        parts.append(_bullet_section("Recommendations", sections["Recommendations"]))

    footer = f"""
  <div class="footer">
    <span>Generated by EagleEye</span>
    <span>{_html.escape(date)}</span>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>EagleEye &mdash; Repo Evaluation &middot; {_html.escape(repo)}</title>
  <style>{_CSS}  </style>
</head>
<body>
<div class="page">
{"".join(parts)}
{footer}
</div>
</body>
</html>"""


def process(md_path: Path) -> Path:
    """Convert an evaluation markdown file to HTML. Returns the output path."""
    content = md_path.read_text(encoding="utf-8")
    fm, rest = _parse_frontmatter(content)
    risk = (fm.get("risk_level") or "unknown").upper()
    sections = _parse_h2_sections(rest)
    html = _build_eval_html(fm, risk, sections, rest)
    out = md_path.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
