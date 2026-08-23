"""Convert EagleEye repo evaluation markdown to styled HTML."""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

from .report import _CSS, _RISK_BORDER, _fmt, _parse_frontmatter

_EVAL_EXTRA_CSS = """
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap');
    body { font-family: 'IBM Plex Sans', system-ui, sans-serif; padding: 28px 20px 72px; background:
      radial-gradient(1200px 500px at 10% -10%, rgba(179,255,71,0.07), transparent 55%),
      radial-gradient(900px 400px at 100% 0%, rgba(255,68,68,0.06), transparent 50%),
      var(--bg); }
    .page { max-width: 920px; }
    .eval-hero { position: relative; overflow: hidden; border-radius: 16px; padding: 32px 36px 28px; margin-bottom: 20px; background: linear-gradient(145deg, #0f2438 0%, #0b1d2e 70%); border: 1.5px solid var(--border); }
    .eval-hero::after { content: ""; position: absolute; inset: auto -20% -40% 40%; height: 180px; background: radial-gradient(circle, rgba(179,255,71,0.12), transparent 65%); pointer-events: none; }
    .eval-hero-top { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; flex-wrap: wrap; position: relative; z-index: 1; }
    .brand { font-size: 12px; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase; color: var(--accent); margin-bottom: 10px; }
    .risk-word { font-size: clamp(40px, 8vw, 64px); font-weight: 700; letter-spacing: -0.04em; line-height: 0.95; margin: 4px 0 10px; animation: riskPulse 1.4s ease-out 1; }
    .risk-word.critical, .risk-word.high { color: var(--crit); }
    .risk-word.medium { color: var(--med); }
    .risk-word.low { color: var(--accent); }
    @keyframes riskPulse { 0% { opacity: 0.35; transform: scale(0.96); } 60% { opacity: 1; transform: scale(1.02); } 100% { opacity: 1; transform: scale(1); } }
    .so-what { font-size: 16px; line-height: 1.45; color: rgba(255,255,255,0.88); max-width: 38rem; margin-bottom: 14px; }
    .grade-rail { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
    .grade-pill { background: rgba(0,0,0,0.28); border: 1px solid var(--border); border-radius: 10px; padding: 8px 12px; min-width: 72px; }
    .grade-pill .lbl { display: block; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
    .grade-pill .val { font-size: 20px; font-weight: 700; font-family: 'IBM Plex Mono', monospace; color: var(--text); }
    .sticky-score { position: sticky; top: 0; z-index: 5; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 10px 14px; margin: 0 0 18px; background: rgba(11,29,46,0.92); border: 1px solid var(--border); border-radius: 10px; backdrop-filter: blur(8px); font-size: 12.5px; color: var(--muted); }
    .sticky-score strong { color: var(--text); }
    .threat-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 22px; }
    .threat-tick { display: block; text-decoration: none; background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; transition: transform 0.15s, border-color 0.15s; animation: fadeUp 0.45s ease both; }
    .threat-tick:hover { transform: translateY(-2px); border-color: var(--accent); text-decoration: none; }
    .threat-tick .n { font-size: 28px; font-weight: 700; font-family: 'IBM Plex Mono', monospace; line-height: 1; }
    .threat-tick .l { font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); margin-top: 6px; }
    .threat-tick.crit .n { color: var(--crit); }
    .threat-tick.high .n { color: var(--high); }
    .threat-tick.med .n { color: var(--med); }
    .threat-tick.ok .n { color: var(--accent); }
    @keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    .beat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 22px; }
    @media (max-width: 720px) { .beat-grid { grid-template-columns: 1fr; } }
    .beat { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
    .beat .k { font-size: 10px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent); margin-bottom: 6px; }
    .beat .v { font-size: 13.5px; color: rgba(255,255,255,0.85); line-height: 1.45; }
    .module-ribbon { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 22px; }
    .mod-chip { position: relative; background: rgba(179,255,71,0.06); border: 1px solid var(--border); border-radius: 999px; padding: 6px 12px; font-size: 12.5px; font-family: 'IBM Plex Mono', monospace; color: var(--accent); cursor: default; }
    .mod-chip:hover::after { content: attr(data-tip); position: absolute; left: 0; top: calc(100% + 8px); z-index: 3; min-width: 200px; max-width: 280px; white-space: normal; background: #07131f; border: 1px solid var(--border); color: rgba(255,255,255,0.85); padding: 8px 10px; border-radius: 8px; font-family: 'IBM Plex Sans', sans-serif; font-size: 12px; line-height: 1.4; box-shadow: 0 8px 24px rgba(0,0,0,0.35); }
    .hit-list { display: flex; flex-direction: column; gap: 8px; }
    .hit { display: grid; grid-template-columns: 6px 1fr; gap: 12px; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; animation: fadeUp 0.4s ease both; }
    .hit .rail { border-radius: 4px; }
    .hit.sev-critical .rail { background: var(--crit); }
    .hit.sev-high .rail { background: var(--high); }
    .hit.sev-medium .rail { background: var(--med); }
    .hit.sev-low .rail { background: var(--low); }
    .hit-title { font-size: 14px; font-weight: 600; color: var(--text); }
    .hit-meta { margin-top: 4px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .do-week { counter-reset: do; }
    .do-item { counter-increment: do; display: grid; grid-template-columns: 28px 1fr; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border); }
    .do-item:last-child { border-bottom: none; }
    .do-item::before { content: counter(do); width: 28px; height: 28px; border-radius: 8px; background: rgba(179,255,71,0.1); border: 1px solid var(--border); color: var(--accent); display: flex; align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 700; }
    .horizon { margin-top: 8px; }
    .horizon > summary { cursor: pointer; list-style: none; color: var(--muted); font-size: 12.5px; font-weight: 600; padding: 8px 0; }
    .horizon > summary:hover { color: var(--accent); }
    .horizon[open] > summary { color: var(--accent); }
    .plan-stack { display: flex; flex-direction: column; gap: 12px; }
    .plan-card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; border-left: 4px solid var(--accent); }
    .plan-card.sev-critical { border-left-color: var(--crit); }
    .plan-card.sev-high { border-left-color: var(--high); }
    .plan-card.sev-medium { border-left-color: var(--med); }
    .plan-head { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
    .plan-num { font-family: 'IBM Plex Mono', monospace; font-weight: 700; color: var(--accent); font-size: 13px; }
    .plan-title { font-size: 15px; font-weight: 600; }
    .plan-block { margin-top: 8px; font-size: 13px; color: rgba(255,255,255,0.82); line-height: 1.5; }
    .plan-block .lbl { display: block; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); margin-bottom: 3px; }
    .action-summary { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
    .action-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
    .action-note { font-size: 13px; color: rgba(255,255,255,0.78); line-height: 1.45; }
    .action-copy { background: rgba(179,255,71,0.12); border: 1px solid var(--border); border-radius: 8px; color: var(--accent); cursor: pointer; font-weight: 700; padding: 7px 12px; }
    .action-copy:hover { border-color: var(--accent); }
    .action-pre { margin: 0; white-space: pre-wrap; font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; line-height: 1.55; color: rgba(255,255,255,0.88); background: rgba(0,0,0,0.22); border-radius: 8px; padding: 12px 14px; }
"""


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


def _first_sentence(text: str, max_len: int = 180) -> str:
    text = (text or "").strip().replace("\n", " ")
    if not text:
        return ""
    for sep in (". ", "! ", "? "):
        if sep in text:
            text = text.split(sep, 1)[0] + sep.strip()
            break
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _parse_grades(body_text: str) -> dict[str, str]:
    security = secrets = pii = ""
    meta_m = re.search(
        r"\*\*Security:\*\*\s*(\S+)\s*\|\s*Secrets:\s*(\S+)\s*\|\s*PII:\s*(\S+)",
        body_text,
    )
    if meta_m:
        security, secrets, pii = meta_m.group(1), meta_m.group(2), meta_m.group(3)
    return {"security": security, "secrets": secrets, "pii": pii}


def _parse_modules(text: str) -> list[dict]:
    mods: list[dict] = []
    for m in re.finditer(
        r"### `([^`]+)`\n(.+?)(?=\n### |\Z)",
        text or "",
        re.DOTALL,
    ):
        name = m.group(1).strip()
        body = m.group(2).strip()
        purpose = body.split("\n", 1)[0].strip()
        mods.append({"name": name, "purpose": purpose})
    return mods


def _parse_remediation_plan(text: str) -> list[dict]:
    steps: list[dict] = []
    if not text:
        return steps
    blocks = re.split(r"(?=^### \d+\. \[)", text, flags=re.MULTILINE)
    for block in blocks:
        block = block.strip()
        hm = re.match(
            r"^### (\d+)\. \[([A-Z]+)\]\s*(.+)$",
            block,
            re.MULTILINE,
        )
        if not hm:
            continue
        body = block[hm.end():]
        files = ""
        files_m = re.search(r"\*\*Files:\*\*\s*(.+?)(?:\n|$)", body)
        if files_m:
            files = files_m.group(1).strip()
        problem = ""
        prob_m = re.search(r"\*\*Problem:\*\*\s*(.+?)(?=\n\*\*|\Z)", body, re.DOTALL)
        if prob_m:
            problem = prob_m.group(1).strip()
        change = ""
        ch_m = re.search(r"\*\*Change plan:\*\*\s*(.+?)(?=\n\*\*|\Z)", body, re.DOTALL)
        if ch_m:
            change = ch_m.group(1).strip()
        check = ""
        ck_m = re.search(r"\*\*Acceptance check:\*\*\s*(.+?)(?=\n\*\*|\Z)", body, re.DOTALL)
        if ck_m:
            check = ck_m.group(1).strip()
        steps.append({
            "priority": hm.group(1),
            "severity": hm.group(2),
            "title": hm.group(3).strip(),
            "files": files,
            "problem": problem,
            "change_plan": change,
            "acceptance_check": check,
        })
    return steps


def _action_summary_text(
    repo: str,
    branch: str,
    date: str,
    plan_steps: list[dict],
    rec_items: list[str],
) -> str:
    lines = [
        f"Implement the agreed EagleEye evaluation for {repo} ({branch}, {date}).",
        "Only change the files named below. Keep existing behavior unless a step says otherwise.",
        "",
    ]
    if plan_steps:
        for step in plan_steps:
            lines.append(f"{step['priority']}. [{step['severity']}] {step['title']}")
            if step.get("files"):
                lines.append(f"   Files: {step['files']}")
            if step.get("change_plan"):
                lines.append(f"   Change: {step['change_plan']}")
            if step.get("acceptance_check"):
                lines.append(f"   Done when: {step['acceptance_check']}")
            lines.append("")
    elif rec_items:
        for index, item in enumerate(rec_items, 1):
            lines.append(f"{index}. {item}")
    return "\n".join(lines).strip()


def _hit_row(finding: dict, delay: int = 0) -> str:
    sev = finding["severity"].lower()
    title = _fmt(finding["title"])
    location = _fmt(finding["location"]) if finding["location"] else ""
    loc_html = f'<span class="fc-file">{location}</span>' if location else ""
    tip = ""
    if finding.get("description") or finding.get("fix"):
        bits = []
        if finding.get("description"):
            bits.append(_fmt(finding["description"]))
        if finding.get("fix"):
            bits.append(f"<strong>Fix:</strong> {_fmt(finding['fix'])}")
        tip = (
            f'<details class="fc-tip"><summary>Details</summary>'
            f'<div class="fc-tip-text">{"".join(bits)}</div></details>'
        )
    return f"""
<div class="hit sev-{sev}" style="animation-delay:{delay}ms">
  <div class="rail"></div>
  <div>
    <div class="hit-title">{title}</div>
    <div class="hit-meta">
      <span class="badge badge-{sev}">{finding['severity']}</span>
      {loc_html}
    </div>
    {tip}
  </div>
</div>"""


def _build_eval_html(fm: dict, risk: str, sections: dict, body_text: str) -> str:
    repo = fm.get("repo", "")
    branch = fm.get("branch", "main")
    date = fm.get("date", "")
    overall = fm.get("overall_grade", "")
    synthesis_failed = fm.get("synthesis_failed", "False").lower() == "true"

    border = _RISK_BORDER.get(risk, "#b3ff47")
    risk_cls = risk.lower()
    repo_url = f"https://github.com/{repo}"
    grades = _parse_grades(body_text)

    summary = _first_sentence(sections.get("Executive summary", ""), 220)
    what = _first_sentence(sections.get("What this repo is", ""), 160)
    why = _first_sentence(sections.get("Problem solved", ""), 160)
    how = sections.get("How it works", "").strip()
    if how:
        how = _first_sentence(how.replace("\n", " "), 200)

    crit = _parse_eval_findings(sections.get("Critical vulnerabilities", ""))
    secs = _parse_eval_findings(sections.get("Secrets & PII risks", ""))
    n_crit = len(crit)
    n_high = sum(1 for f in crit + secs if f["severity"].upper() == "HIGH")
    n_med = sum(1 for f in crit + secs if f["severity"].upper() == "MEDIUM")
    n_sec = len(secs)

    modules = _parse_modules(sections.get("Modules analyzed", ""))

    grade_pills = []
    if overall:
        grade_pills.append(("Overall", overall))
    if grades["security"]:
        grade_pills.append(("Security", grades["security"]))
    if grades["secrets"]:
        grade_pills.append(("Secrets", grades["secrets"]))
    if grades["pii"]:
        grade_pills.append(("PII", grades["pii"]))
    pills_html = "".join(
        f'<div class="grade-pill"><span class="lbl">{_html.escape(l)}</span>'
        f'<span class="val">{_html.escape(v)}</span></div>'
        for l, v in grade_pills
    )

    hero = f"""
  <div class="eval-hero" style="border-color:{border}">
    <div class="eval-hero-top">
      <div>
        <div class="brand">EagleEye Repo Evaluation</div>
        <div class="risk-word {risk_cls}">{_html.escape(risk)}</div>
        <h1 style="font-size:18px;font-weight:600;margin:0 0 10px;color:rgba(255,255,255,0.92)">{_html.escape(repo)}</h1>
        <p class="so-what">{_fmt(summary) or "Evaluation complete."}</p>
        <div class="grade-rail">{pills_html}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;align-items:flex-end">
        <a href="{repo_url}" target="_blank" class="pr-link">View on GitHub &#8599;</a>
        <span style="font-size:12px;color:var(--muted)">{_html.escape(branch)} · {_html.escape(date)}</span>
        {"<span style='font-size:12px;color:var(--muted)'>Deterministic-only</span>" if synthesis_failed else ""}
      </div>
    </div>
  </div>"""

    sticky = f"""
  <div class="sticky-score">
    <span class="badge badge-{risk_cls}">{_html.escape(risk)} RISK</span>
    <span><strong>{_html.escape(overall or "—")}</strong> overall</span>
    <span>{n_crit} critical</span>
    <span>{n_sec} secrets/PII</span>
    <span>{len(modules)} modules</span>
  </div>"""

    rec_text = sections.get("Recommendations", "")
    rec_items = [line.strip()[2:] for line in rec_text.splitlines() if line.strip().startswith("- ")]
    plan_steps = _parse_remediation_plan(sections.get("Remediation plan", ""))
    action_text = _action_summary_text(repo, branch, date, plan_steps, rec_items)
    n_actions = len(plan_steps) or len(rec_items)

    threat = f"""
  <div class="threat-strip">
    <a class="threat-tick crit" href="#hits-critical" style="animation-delay:40ms"><div class="n">{n_crit}</div><div class="l">Critical</div></a>
    <a class="threat-tick high" href="#hits-secrets" style="animation-delay:90ms"><div class="n">{n_high}</div><div class="l">High</div></a>
    <a class="threat-tick med" href="#hits-secrets" style="animation-delay:140ms"><div class="n">{n_med}</div><div class="l">Medium</div></a>
    <a class="threat-tick ok" href="#hits-secrets" style="animation-delay:190ms"><div class="n">{n_sec}</div><div class="l">Secrets/PII</div></a>
    <a class="threat-tick ok" href="#action-summary" style="animation-delay:240ms"><div class="n">{n_actions}</div><div class="l">Actions</div></a>
  </div>"""

    beats = ""
    if what or why or how:
        beats = f"""
  <div class="beat-grid">
    <div class="beat"><div class="k">What</div><div class="v">{_fmt(what) or "—"}</div></div>
    <div class="beat"><div class="k">Why</div><div class="v">{_fmt(why) or "—"}</div></div>
    <div class="beat"><div class="k">Flow</div><div class="v">{_fmt(how) or "—"}</div></div>
  </div>"""

    ribbon = ""
    if modules:
        chips = "".join(
            f'<span class="mod-chip" data-tip="{_html.escape(_first_sentence(m["purpose"], 120))}">{_html.escape(m["name"])}</span>'
            for m in modules[:10]
        )
        ribbon = f"""
  <section>
    <div class="section-title">Modules</div>
    <div class="module-ribbon">{chips}</div>
  </section>"""

    parts = [hero, sticky, threat, beats, ribbon]

    if crit:
        hits = "".join(_hit_row(f, i * 40) for i, f in enumerate(crit))
        parts.append(f"""
  <section id="hits-critical">
    <div class="section-title">Critical hits</div>
    <div class="hit-list">{hits}</div>
  </section>""")
    elif "Critical vulnerabilities" in sections:
        parts.append("""
  <section id="hits-critical">
    <div class="section-title">Critical hits</div>
    <div class="card">None identified.</div>
  </section>""")

    if secs:
        hits = "".join(_hit_row(f, i * 40) for i, f in enumerate(secs))
        parts.append(f"""
  <section id="hits-secrets">
    <div class="section-title">Secrets &amp; PII</div>
    <div class="hit-list">{hits}</div>
  </section>""")

    if rec_items:
        top = rec_items[:5]
        do_html = "".join(f'<div class="do-item"><div>{_fmt(item)}</div></div>' for item in top)
        more = ""
        if len(rec_items) > 5:
            rest = "".join(f"<li>{_fmt(item)}</li>" for item in rec_items[5:])
            more = f'<details class="horizon"><summary>+{len(rec_items) - 5} more recommendations</summary><ul style="margin:8px 0 0 18px">{rest}</ul></details>'
        parts.append(f"""
  <section id="do-this-week">
    <div class="section-title">Do this week</div>
    <div class="card do-week">{do_html}{more}</div>
  </section>""")

    if plan_steps:
        cards = []
        for step in plan_steps:
            sev = step["severity"].lower()
            cards.append(f"""
<div class="plan-card sev-{sev}">
  <div class="plan-head">
    <span class="plan-num">#{_html.escape(step['priority'])}</span>
    <span class="badge badge-{sev}">{_html.escape(step['severity'])}</span>
    <span class="plan-title">{_fmt(step['title'])}</span>
  </div>
  <div class="plan-block"><span class="lbl">Files</span>{_fmt(step['files']) or 'n/a'}</div>
  <div class="plan-block"><span class="lbl">Problem</span>{_fmt(step['problem'])}</div>
  <div class="plan-block"><span class="lbl">Change the code</span>{_fmt(step['change_plan'])}</div>
  <div class="plan-block"><span class="lbl">Acceptance check</span>{_fmt(step['acceptance_check'])}</div>
</div>""")
        parts.append(f"""
  <section id="remediation-plan">
    <div class="section-title">Remediation plan — change the code</div>
    <div class="plan-stack">{"".join(cards)}</div>
  </section>""")

    horizon_bits = []
    stated = sections.get("Future scope (stated by author)", "").strip()
    inferred = sections.get("Future scope (inferred)", "").strip()
    if stated and stated not in ("_None stated in README/docs._",):
        horizon_bits.append(f"<p><strong>Stated:</strong> {_fmt(stated)}</p>")
    if inferred and inferred not in ("_N/A_",):
        horizon_bits.append(f"<p><strong>Inferred:</strong> {_fmt(inferred)}</p>")
    if horizon_bits:
        parts.append(f"""
  <details class="horizon">
    <summary>Horizon — future scope</summary>
    <div class="card" style="margin-top:8px">{"".join(horizon_bits)}</div>
  </details>""")

    cov = sections.get("Coverage", "").strip()
    if cov:
        parts.append(f"""
  <section>
    <div class="section-title">Coverage</div>
    <div class="card">{_fmt(cov)}</div>
  </section>""")

    if action_text:
        parts.append(f"""
  <section id="action-summary">
    <div class="section-title">Action summary</div>
    <div class="action-summary">
      <div class="action-toolbar">
        <p class="action-note">Copy this pack if you agree with the analysis. Paste it into an agent or ticket to implement only these changes.</p>
        <button class="action-copy" id="copy-action-summary" type="button">Copy action summary</button>
      </div>
      <pre class="action-pre" id="action-summary-text">{_html.escape(action_text)}</pre>
    </div>
  </section>""")

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
  <style>{_CSS}
{_EVAL_EXTRA_CSS}
  </style>
</head>
<body>
<div class="page">
{"".join(parts)}
{footer}
</div>
<script>
(function () {{
  var btn = document.getElementById("copy-action-summary");
  var text = document.getElementById("action-summary-text");
  if (!btn || !text) return;
  btn.addEventListener("click", function () {{
    var payload = text.textContent || "";
    var done = function () {{
      btn.textContent = "Copied";
      setTimeout(function () {{ btn.textContent = "Copy action summary"; }}, 1600);
    }};
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(payload).then(done).catch(function () {{
        window.getSelection().selectAllChildren(text);
      }});
    }} else {{
      window.getSelection().selectAllChildren(text);
    }}
  }});
}})();
</script>
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
