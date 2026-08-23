"""EagleEye Cockpit — generate reviews/index.html from saved PR reviews and repo evaluations."""

from __future__ import annotations

import html
import os
import re
from datetime import datetime
from pathlib import Path

from ...core.paths import evaluations_root, reviews_root

REVIEWS_DIR = reviews_root()
EVALUATIONS_DIR = evaluations_root()

_VERDICT_META = {
    "approve":          {"label": "Approved ✅",        "cls": "approve",  "emoji": "✅"},
    "request_changes":  {"label": "Needs Changes ❌",   "cls": "block",    "emoji": "❌"},
    "comment":          {"label": "Needs Attention 💬", "cls": "comment",  "emoji": "💬"},
    "unknown":          {"label": "Unknown",            "cls": "unknown",  "emoji": "◯"},
}

_RISK_META = {
    "CRITICAL": {"cls": "crit",    "color": "#ff4444"},
    "HIGH":     {"cls": "high",    "color": "#ff8800"},
    "MEDIUM":   {"cls": "med",     "color": "#ffcc00"},
    "LOW":      {"cls": "low",     "color": "#44cc88"},
    "UNKNOWN":  {"cls": "unknown", "color": "#7fafc0"},
}

_STATUS_STYLE = {
    "open":   ("color:#44aaff", "OPEN"),
    "merged": ("color:#44cc88", "MERGED"),
    "closed": ("color:#ff8800", "CLOSED"),
}


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _live_artifact_href(kind: str, relative: str) -> str:
    normalized = str(relative).replace("\\", "/")
    if kind == "evaluation":
        marker = "evaluations/"
        if marker in normalized:
            normalized = normalized.split(marker, 1)[1]
        return "/artifacts/evaluations/" + normalized.lstrip("/")
    return "/artifacts/reviews/" + normalized.lstrip("/")


def _safe_href(value: str, *, live: bool = False, kind: str = "review") -> str:
    raw = (value or "").strip()
    if not raw:
        return "#"
    if live:
        raw = _live_artifact_href(kind, raw)
    if raw.lower().startswith(("javascript:", "data:", "vbscript:")):
        return "#"
    return html.escape(raw, quote=True)


def _parse_fm(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    fm: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            if key.strip():
                fm[key.strip()] = val.strip()
    return fm


def _extract_verdict_risk(text: str) -> tuple[str, str]:
    m = re.search(r"\*\*Review:\*\*\s*(.+?)\s*(?:&nbsp;·&nbsp;|\s*·\s*)\s*\*\*Risk:\*\*\s*`([^`]+)`", text)
    if m:
        raw = m.group(1).strip()
        risk = m.group(2).strip().upper()
        if "✅" in raw or "okay" in raw.lower() or "approve" in raw.lower():
            verdict = "approve"
        elif "💬" in raw or "attention" in raw.lower() or "comment" in raw.lower():
            verdict = "comment"
        elif "❌" in raw or "revisit" in raw.lower() or "changes" in raw.lower():
            verdict = "request_changes"
        else:
            verdict = "unknown"
        return verdict, risk
    if "## EagleEye Code Review ✅" in text:
        return "approve", _fallback_risk(text)
    if "## EagleEye Code Review 💬" in text:
        return "comment", _fallback_risk(text)
    if "## EagleEye Code Review ❌" in text:
        return "request_changes", _fallback_risk(text)
    if "**Needs attention**" in text:
        return "comment", _fallback_risk(text)
    return "unknown", "UNKNOWN"


def _fallback_risk(text: str) -> str:
    m = re.search(r"Risk:\s*`?([A-Z]+)`?", text)
    return m.group(1).upper() if m else "UNKNOWN"


def _resolve_timestamp(fm: dict, mtime: float) -> float:
    """Return a reliable Unix timestamp for a review.

    Priority:
    1. timestamp_utc frontmatter field (set by _save_review since this fix)
    2. Parse 'date' field — strip tz abbreviation, treat as local time
    3. Fall back to file mtime
    """
    if ts := fm.get("timestamp_utc"):
        try:
            return float(ts)
        except ValueError:
            pass

    date_str = fm.get("date", "")
    if date_str:
        # Strip trailing timezone abbreviation (e.g. "IST", "UTC", "PST")
        clean = re.sub(r'\s+[A-Z]{2,5}$', '', date_str.strip())
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(clean, fmt)
                # Treat as local time — compare with local now in JS/Python
                return dt.replace(tzinfo=datetime.now().astimezone().tzinfo).timestamp()
            except ValueError:
                continue

    return mtime


def _scan_reviews() -> list[dict]:
    rows = []
    root = reviews_root()
    for md in root.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        fm = _parse_fm(text)
        if not fm.get("repo"):
            continue
        verdict, risk = _extract_verdict_risk(text)
        html_path = md.with_suffix(".html")
        html_rel = str(html_path.relative_to(root)) if html_path.exists() else ""
        md_rel   = str(md.relative_to(root))
        ts = _resolve_timestamp(fm, md.stat().st_mtime)

        cost = 0.0
        try:
            cost = float(fm.get("cost_usd", 0) or 0)
        except ValueError:
            pass

        repo_slug = fm.get("repo", "")
        slug_parts = repo_slug.split("/", 1)
        owner     = slug_parts[0] if len(slug_parts) == 2 else ""
        repo_name = slug_parts[1] if len(slug_parts) == 2 else repo_slug
        pr_raw = fm.get("pr", "")
        try:
            pr_number = int(pr_raw)
        except (ValueError, TypeError):
            pr_number = 0

        rows.append({
            "repo":           repo_slug,
            "owner":          owner,
            "repo_name":      repo_name,
            "pr":             pr_raw,
            "pr_number":      pr_number,
            "title":          fm.get("title", f"PR #{pr_raw or '?'}"),
            "date":           fm.get("date", ""),
            "timestamp":      ts,
            "url":            fm.get("url", ""),
            "by":             fm.get("requested_by", ""),
            "verdict":        verdict,
            "risk":           risk,
            "html":           html_rel,
            "md":             md_rel,
            "files_analyzed": fm.get("files_analyzed", ""),
            "pr_status":      fm.get("pr_status", ""),
            "cost_usd":       cost,
        })

    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return rows


def _group_reviews(rows: list[dict]) -> list[dict]:
    """Group flat review rows by (repo, pr_number). One entry per PR.

    Primary entry = latest run (rows is sorted by timestamp desc).
    Attaches last 3 runs as 'history' list for the card to render.
    """
    from collections import defaultdict

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["repo"], str(row["pr"]))
        groups[key].append(row)

    result = []
    for runs in groups.values():
        primary = dict(runs[0])       # latest run is the card's primary data
        primary["history"] = runs[:3] # last 3 runs (newest first)
        result.append(primary)

    result.sort(key=lambda r: r["timestamp"], reverse=True)
    return result


def _extract_eval_summary(text: str) -> str:
    m = re.search(r"## Executive summary\n\n(.+?)(?:\n\n##|\Z)", text, re.DOTALL)
    if m:
        raw = m.group(1).strip().replace("\n", " ")
    else:
        m = re.search(r"## What this repo is\n\n(.+?)(?:\n\n##|\Z)", text, re.DOTALL)
        raw = m.group(1).strip().replace("\n", " ") if m else "Repo evaluation"
    for sep in (". ", "! ", "? "):
        if sep in raw:
            raw = raw.split(sep, 1)[0] + sep.strip()
            break
    return raw[:120] + ("…" if len(raw) > 120 else "")


def _scan_evaluations() -> list[dict]:
    rows = []
    root = evaluations_root()
    if not root.exists():
        return rows
    for md in root.rglob("eval-*.md"):
        text = md.read_text(encoding="utf-8")
        fm = _parse_fm(text)
        if not fm.get("repo"):
            continue
        html_path = md.with_suffix(".html")
        if not html_path.exists():
            try:
                from .eval_report import process as _generate_eval_html
                _generate_eval_html(md)
            except Exception:
                pass
        ts = _resolve_timestamp(fm, md.stat().st_mtime)
        risk = (fm.get("risk_level") or "unknown").upper()
        md_rel = Path(os.path.relpath(md.resolve(), reviews_root().resolve())).as_posix()
        html_rel = (
            Path(os.path.relpath(html_path.resolve(), reviews_root().resolve())).as_posix()
            if html_path.exists() else ""
        )
        repo_slug = fm.get("repo", "")
        rows.append({
            "repo": repo_slug,
            "branch": fm.get("branch", "main"),
            "date": fm.get("date", ""),
            "timestamp": ts,
            "risk": risk,
            "grade": fm.get("overall_grade", "") or "",
            "html": html_rel,
            "md": md_rel,
            "summary": _extract_eval_summary(text),
            "synthesis_failed": fm.get("synthesis_failed", "False").lower() == "true",
            "scoped_path": fm.get("scoped_path", ""),
        })
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return rows


def _group_evaluations(rows: list[dict]) -> list[dict]:
    from collections import defaultdict

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["repo"]].append(row)

    result = []
    for runs in groups.values():
        primary = dict(runs[0])
        primary["history"] = runs[:3]
        result.append(primary)
    result.sort(key=lambda r: r["timestamp"], reverse=True)
    return result


def _eval_card(r: dict, live: bool = False) -> str:
    rm = _RISK_META.get(r["risk"], _RISK_META["UNKNOWN"])
    repo_url = f"https://github.com/{_esc(r['repo'])}"
    ts = int(r["timestamp"])
    grade = _esc(r.get("grade") or "—")
    scope_tag = (
        f'<span class="files-badge">📁 {_esc(r["scoped_path"])}</span>'
        if r.get("scoped_path") else ""
    )
    llm_tag = (
        '<span class="files-badge">⚡ no LLM</span>'
        if r.get("synthesis_failed") else ""
    )
    history_html = ""
    history = r.get("history", [])
    if len(history) > 1:
        prev_links = ""
        for run in history[1:]:
            href = _safe_href(
                run["html"] if run.get("html") else run["md"],
                live=live,
                kind="evaluation",
            )
            prev_links += (
                f'<a href="{href}" target="_blank" class="run-link">'
                f'{_esc(run["date"] or "prev")} ↗</a>'
            )
        history_html = f'<div class="run-history"><span class="run-history-label">Prev runs:</span>{prev_links}</div>'

    report_href = _safe_href(r["html"] if r.get("html") else r["md"], live=live, kind="evaluation")
    if report_href:
        report_href = f"{report_href}#action-summary"

    return f"""
<div class="pr-card eval-card risk-{rm['cls']}" style="border-left-color:{rm['color']}" data-ts="{ts}" data-risk="{_esc(r['risk'].lower())}" data-type="evaluation">
  <div class="card-top">
    <div class="card-badges">
      <span class="risk-badge" style="background:{rm['color']}22;color:{rm['color']};border-color:{rm['color']}55;font-size:11px;padding:4px 10px">{_esc(r['risk'])}</span>
      <span class="verdict-badge" style="background:rgba(179,255,71,0.08);color:var(--accent);border:1px solid var(--border)">Grade {grade}</span>
      <span class="files-badge">Latest</span>
    </div>
    <span class="time-ago" data-ts="{ts}" title="{_esc(r['date'])}">…</span>
  </div>
  <div class="card-title" style="font-size:15px;letter-spacing:-0.01em">{_esc(r['repo'])}</div>
  <div style="font-size:13px;color:rgba(232,244,255,0.78);line-height:1.4">{_esc(r['summary'])}</div>
  <div class="card-meta">
    <a href="{repo_url}" target="_blank" class="repo-link">{_esc(r['repo'])}</a>
    <span class="files-badge">🌿 {_esc(r['branch'])}</span>
    {scope_tag}
    {llm_tag}
  </div>
  <div class="card-footer">
    <span class="reviewed-at">🕐 {_esc(r['date'])}</span>
    <span class="card-actions">
      <button class="open-btn rerun-evaluation" style="cursor:pointer" type="button" data-repo="{_esc(r['repo'])}" data-branch="{_esc(r['branch'])}" data-path="{_esc(r.get('scoped_path', ''))}">Re-run</button>
      <a href="{report_href}" target="_blank" class="open-btn">Open Report</a>
    </span>
  </div>
  {history_html}
</div>"""


def _stat_card(label: str, value: str, accent: str = "#b3ff47", stat_id: str = "") -> str:
    id_attr = f' id="{stat_id}"' if stat_id else ""
    return (
        f'<div class="stat-card">'
        f'<div class="stat-val" style="color:{accent}"{id_attr}>{value}</div>'
        f'<div class="stat-label">{label}</div>'
        f'</div>'
    )


def _pr_card(r: dict, live: bool = False) -> str:
    vm = _VERDICT_META.get(r["verdict"], _VERDICT_META["unknown"])
    rm = _RISK_META.get(r["risk"], _RISK_META["UNKNOWN"])
    repo_url    = f"https://github.com/{_esc(r['repo'])}"
    report_href = _safe_href(r["html"] if r["html"] else r["md"], live=live, kind="review")
    ts          = int(r["timestamp"])
    by_tag      = f'<span class="by">@{_esc(r["by"])}</span>' if r["by"] else ""
    files_tag = (
        f'<span class="files-badge">📂 {_esc(r["files_analyzed"])} files</span>'
        if r["files_analyzed"] else ""
    )
    pr_href = _esc(r["url"]) if str(r.get("url") or "").startswith(("http://", "https://")) else ""
    pr_link     = (
        f'<a href="{pr_href}" target="_blank" class="pr-num-link">#{_esc(r["pr"])}</a>'
        if pr_href else f'<span class="pr-num-link">#{_esc(r["pr"])}</span>'
    )

    # PR status badge
    status_tag = ""
    if r["pr_status"]:
        style, label = _STATUS_STYLE.get(r["pr_status"].lower(), ("color:var(--muted)", r["pr_status"].upper()))
        status_tag = f'<span class="status-badge" style="{style}">{_esc(label)}</span>'

    # Cost tag
    cost_tag = ""
    if r["cost_usd"] > 0:
        cost_tag = f'<span class="cost-badge">💰 ${r["cost_usd"]:.4f}</span>'

    # History strip — previous runs (history[0] is latest, already shown by Open Report button)
    history_html = ""
    history = r.get("history", [])
    if len(history) > 1:
        prev_links = ""
        for run in history[1:]:  # skip history[0] (= latest)
            href = _safe_href(run["html"] if run["html"] else run["md"], live=live, kind="review")
            label = _esc(run["date"] or "prev")
            prev_links += f'<a href="{href}" target="_blank" class="run-link" title="{label}">{label} ↗</a>'
        history_html = f'<div class="run-history"><span class="run-history-label">Prev runs:</span>{prev_links}</div>'

    return f"""
<div class="pr-card risk-{rm['cls']}" style="border-left-color:{rm['color']}" data-ts="{ts}" data-status="{_esc(r['pr_status'])}" data-verdict="{_esc(r['verdict'])}" data-risk="{_esc(r['risk'].lower())}" data-cost="{r['cost_usd']}">
  <div class="card-top">
    <div class="card-badges">
      <span class="verdict-badge v-{vm['cls']}">{vm['emoji']} {vm['label']}</span>
      <span class="risk-badge" style="background:{rm['color']}20;color:{rm['color']};border-color:{rm['color']}40">{_esc(r['risk'])} RISK</span>
      {status_tag}
    </div>
    <span class="time-ago" data-ts="{ts}" title="{_esc(r['date'])}">…</span>
  </div>
  <div class="card-title">{pr_link} · {_esc(r['title'])}</div>
  <div class="card-meta">
    <a href="{repo_url}" target="_blank" class="repo-link">{_esc(r['repo'])}</a>
    {by_tag}
    {files_tag}
    {cost_tag}
  </div>
  <div class="card-footer">
    <span class="reviewed-at">🕐 {_esc(r['date'])}</span>
    <span class="card-actions">
      <button class="open-btn rerun-review" style="cursor:pointer" type="button" data-owner="{_esc(r['owner'])}" data-repo="{_esc(r['repo_name'])}" data-pr="{int(r['pr_number'])}">Re-run</button>
      <a href="{report_href}" target="_blank" class="open-btn">Open Report</a>
    </span>
  </div>
  {history_html}
</div>"""


def build_dashboard(live: bool = False) -> Path:
    rows = _scan_reviews()
    grouped = _group_reviews(rows)
    eval_rows = _scan_evaluations()
    eval_grouped = _group_evaluations(eval_rows)
    now_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    total      = len(grouped)
    approved   = sum(1 for r in grouped if r["verdict"] == "approve")
    blocked    = sum(1 for r in grouped if r["verdict"] == "request_changes")
    comment    = sum(1 for r in grouped if r["verdict"] == "comment")
    critical   = sum(1 for r in grouped if r["risk"] in ("CRITICAL", "HIGH"))
    total_cost = sum(r["cost_usd"] for r in grouped)

    eval_total = len(eval_grouped)
    eval_critical = sum(1 for r in eval_grouped if r["risk"] in ("CRITICAL", "HIGH"))

    cost_display = f"${total_cost:.2f}" if total_cost > 0 else "—"
    review_stats_html = "".join([
        _stat_card("Total Reviews",   str(total),    "#b3ff47", "stat-total"),
        _stat_card("Approved",        str(approved), "#44cc88", "stat-approved"),
        _stat_card("Needs Changes",   str(blocked),  "#ff4444", "stat-blocked"),
        _stat_card("Needs Attention", str(comment),  "#ffcc00", "stat-comment"),
        _stat_card("High/Critical",   str(critical), "#ff8800", "stat-critical"),
        _stat_card("Total Cost",      cost_display,  "#b3ff47", "stat-cost"),
    ])
    eval_stats_html = "".join([
        _stat_card("Total Evaluations", str(eval_total), "#b3ff47", "estat-total"),
        _stat_card("High/Critical",     str(eval_critical), "#ff8800", "estat-critical"),
        _stat_card("Repos Assessed",    str(eval_total), "#44cc88", "estat-repos"),
    ])

    cards_html = "".join(_pr_card(r, live=live) for r in grouped)
    if not cards_html:
        cards_html = '<div class="empty">No PR reviews found — run <code>eagleeye review owner/repo 42</code>.</div>'

    eval_cards_html = "".join(_eval_card(r, live=live) for r in eval_grouped)
    if not eval_cards_html:
        eval_cards_html = '<div class="empty">No evaluations found — run <code>eagleeye evaluate owner/repo</code>.</div>'

    record_count = f"{total} review{'' if total == 1 else 's'}"
    if eval_total:
        record_count += f" · {eval_total} evaluation{'' if eval_total == 1 else 's'}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EagleEye Cockpit</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:      #07131f;
    --panel:   #0c1e2e;
    --card:    #0f2438;
    --accent:  #b3ff47;
    --text:    #e8f4ff;
    --muted:   #5a8aaa;
    --border:  rgba(179,255,71,0.15);
    --approve: #44cc88;
    --block:   #ff4444;
    --comment: #ffcc00;
  }}
  body {{ background: var(--bg); color: var(--text); font-family: 'SF Pro Display', 'Inter', system-ui, sans-serif; min-height: 100vh; }}

  .header {{ background: var(--panel); border-bottom: 1px solid var(--border); padding: 18px 32px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 10; backdrop-filter: blur(8px); }}
  .logo {{ display: flex; align-items: center; gap: 12px; }}
  .logo-eye {{ width: 36px; height: 36px; background: var(--accent); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; }}
  .logo-text {{ font-size: 20px; font-weight: 700; letter-spacing: -0.02em; }}
  .logo-sub  {{ font-size: 11px; color: var(--muted); font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; }}
  .header-right {{ text-align: right; font-size: 12px; color: var(--muted); }}
  .header-right strong {{ color: var(--accent); }}

  .stats-strip {{ display: flex; gap: 12px; padding: 20px 32px; background: var(--panel); border-bottom: 1px solid var(--border); flex-wrap: wrap; }}
  .stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 20px; min-width: 110px; flex: 1; }}
  .stat-val   {{ font-size: 28px; font-weight: 700; letter-spacing: -0.03em; }}
  .stat-label {{ font-size: 11px; color: var(--muted); margin-top: 2px; text-transform: uppercase; letter-spacing: 0.06em; }}

  .toolbar {{ padding: 14px 32px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; border-bottom: 1px solid var(--border); }}
  .toolbar-title {{ font-size: 12px; color: var(--muted); flex: 1; }}
  .filter-btn {{ background: var(--card); border: 1px solid var(--border); border-radius: 20px; padding: 5px 13px; font-size: 12px; color: var(--muted); cursor: pointer; transition: all 0.15s; }}
  .filter-btn:hover, .filter-btn.active {{ background: rgba(179,255,71,0.1); border-color: var(--accent); color: var(--accent); }}
  .filter-sep {{ width: 1px; height: 20px; background: var(--border); margin: 0 4px; flex-shrink: 0; }}

  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; padding: 20px 32px 40px; }}

  .pr-card {{ background: var(--card); border: 1px solid var(--border); border-left: 4px solid #555; border-radius: 12px; padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; transition: transform 0.15s, box-shadow 0.15s; }}
  .pr-card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 32px rgba(0,0,0,0.4); }}
  .card-top {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }}
  .card-badges {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
  .verdict-badge {{ font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 20px; white-space: nowrap; }}
  .v-approve {{ background: rgba(68,204,136,0.15); color: var(--approve); border: 1px solid rgba(68,204,136,0.3); }}
  .v-block   {{ background: rgba(255,68,68,0.12);  color: var(--block);   border: 1px solid rgba(255,68,68,0.3); }}
  .v-comment {{ background: rgba(255,204,0,0.12);  color: var(--comment); border: 1px solid rgba(255,204,0,0.3); }}
  .v-unknown {{ background: rgba(90,138,170,0.12); color: var(--muted);   border: 1px solid rgba(90,138,170,0.3); }}
  .risk-badge {{ font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 20px; border: 1px solid transparent; letter-spacing: 0.04em; }}
  .status-badge {{ font-size: 10px; font-weight: 700; letter-spacing: 0.04em; }}
  .time-ago {{ font-size: 11px; color: var(--muted); white-space: nowrap; flex-shrink: 0; margin-top: 4px; }}
  .card-title {{ font-size: 14px; font-weight: 600; line-height: 1.4; color: var(--text); }}
  .pr-num-link {{ color: var(--accent); text-decoration: none; font-weight: 700; }}
  .pr-num-link:hover {{ text-decoration: underline; }}
  .card-meta {{ display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--muted); flex-wrap: wrap; }}
  .repo-link {{ color: var(--muted); text-decoration: none; font-family: monospace; font-size: 11.5px; }}
  .repo-link:hover {{ color: var(--accent); }}
  .by {{ background: rgba(179,255,71,0.08); border: 1px solid var(--border); border-radius: 20px; padding: 1px 8px; font-size: 10.5px; color: var(--accent); }}
  .files-badge {{ background: rgba(90,138,170,0.12); border: 1px solid rgba(90,138,170,0.25); border-radius: 20px; padding: 1px 8px; font-size: 10.5px; color: var(--muted); }}
  .cost-badge {{ background: rgba(179,255,71,0.06); border: 1px solid var(--border); border-radius: 20px; padding: 1px 8px; font-size: 10.5px; color: var(--muted); }}
  .card-footer {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 4px; border-top: 1px solid var(--border); padding-top: 10px; flex-wrap: nowrap; }}
  .reviewed-at {{ font-size: 11px; color: var(--muted); flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .card-actions {{ display: flex; align-items: center; gap: 6px; flex: 0 0 auto; flex-wrap: nowrap; }}
  .open-btn {{ display: inline-flex; align-items: center; background: rgba(179,255,71,0.1); border: 1px solid var(--border); border-radius: 8px; padding: 5px 10px; font-size: 12px; color: var(--accent); text-decoration: none; font-weight: 600; transition: all 0.15s; white-space: nowrap; flex: 0 0 auto; }}
  .open-btn:hover {{ background: rgba(179,255,71,0.2); border-color: var(--accent); }}
  .empty {{ grid-column: 1/-1; text-align: center; padding: 60px; color: var(--muted); font-size: 15px; }}
  .run-history {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }}
  .run-history-label {{ font-size: 11px; color: var(--muted); white-space: nowrap; }}
  .run-link {{ font-size: 11px; color: var(--accent); text-decoration: none; background: rgba(179,255,71,0.06); border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px; white-space: nowrap; }}
  .run-link:hover {{ background: rgba(179,255,71,0.14); border-color: var(--accent); }}
  .search-input {{ background: rgba(15,36,56,0.8); border: 1px solid var(--border); border-radius: 20px; color: var(--text); padding: 7px 16px 7px 36px; font-size: 13px; width: 240px; outline: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%235a8aaa' stroke-width='2'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.35-4.35'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: 12px center; transition: border-color 0.15s, width 0.2s; }}
  .search-input:focus {{ border-color: var(--accent); width: 300px; }}
  .search-input::placeholder {{ color: var(--muted); }}
  .pr-card.hidden {{ display: none; }}
  .tab-bar {{ display: flex; gap: 8px; padding: 12px 32px 0; border-bottom: 1px solid var(--border); background: var(--panel); }}
  .tab-btn {{ background: transparent; border: none; border-bottom: 2px solid transparent; color: var(--muted); padding: 10px 16px; font-size: 13px; font-weight: 600; cursor: pointer; }}
  .tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}
  .run-panel {{ margin: 20px 32px 0; padding: 16px 20px; background: var(--panel); border: 1px solid var(--border); border-radius: 12px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .run-panel input {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; color: var(--text); padding: 8px 10px; outline: none; min-width: 120px; }}
  .run-panel input:focus {{ border-color: var(--accent); }}
  .run-panel button {{ background: var(--accent); border: 0; border-radius: 8px; color: var(--bg); cursor: pointer; font-weight: 700; padding: 9px 15px; }}
  .run-panel button:disabled {{ cursor: wait; opacity: 0.5; }}
  .run-panel .refresh-btn {{ background: transparent; border: 1px solid var(--border); color: var(--accent); }}
  .run-panel .refresh-btn:hover {{ background: rgba(179,255,71,0.12); }}
  .run-controls {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; width: 100%; }}
  .run-options {{ display: flex; align-items: center; gap: 10px; color: var(--muted); font-size: 11px; }}
  .run-options input {{ min-width: auto; }}
  .run-divider {{ width: 100%; border-top: 1px solid var(--border); }}
  .run-state {{ color: var(--muted); flex: 1; font-size: 12px; min-width: 240px; }}
  .run-state[data-status="completed"] {{ color: var(--approve); }}
  .run-state[data-status="failed"] {{ color: var(--block); }}
</style>
</head>
<body>

<div class="header">
  <div class="logo">
    <div class="logo-eye">🦅</div>
    <div>
      <div class="logo-text">EagleEye</div>
      <div class="logo-sub">Command Center</div>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:20px">
    <input class="search-input" type="text" placeholder="Search repo or title…" oninput="doSearch(this.value)" />
    <div class="header-right">
      <div>Last refreshed: <strong>{now_str}</strong></div>
      <div style="margin-top:3px">{record_count} on record</div>
    </div>
  </div>
</div>

<div class="run-panel">
  <form class="run-controls" id="run-form" onsubmit="startReview(event)">
    <strong>Run PR review</strong>
    <input id="run-owner" required placeholder="owner" aria-label="Repository owner" />
    <input id="run-repo" required placeholder="repository" aria-label="Repository name" />
    <input id="run-pr" required min="1" type="number" placeholder="PR #" aria-label="Pull request number" style="min-width:80px;width:90px" />
    <button id="run-button" type="submit">Review</button>
  </form>
  <div class="run-divider"></div>
  <form class="run-controls" id="evaluate-form" onsubmit="startEvaluation(event)">
    <strong>Run repo evaluation</strong>
    <input id="eval-owner" required placeholder="owner" aria-label="Evaluation repository owner" />
    <input id="eval-repo" required placeholder="repository" aria-label="Evaluation repository name" />
    <input id="eval-branch" placeholder="branch (default)" aria-label="Evaluation branch" />
    <input id="eval-path" placeholder="path (optional)" aria-label="Evaluation path scope" />
    <span class="run-options">
      <label><input id="eval-quick" type="checkbox" /> Quick</label>
      <label><input id="eval-no-llm" type="checkbox" /> No LLM</label>
      <label><input id="eval-data" type="checkbox" /> Include data dirs</label>
    </span>
    <button id="evaluate-button" type="submit">Evaluate</button>
    <button id="refresh-button" class="refresh-btn" type="button" onclick="refreshForms()">Refresh</button>
  </form>
  <button id="feedback-button" type="button" style="display:none" onclick="recordFeedback()">Record feedback</button>
  <span class="run-state" id="run-state">Live status is available when opened with <code>eagleeye cockpit</code>.</span>
  <span class="run-state" id="pilot-metrics"></span>
</div>

<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('reviews', this)">PR Reviews ({total})</button>
  <button class="tab-btn" onclick="switchTab('evaluations', this)">Repo Evaluations ({eval_total})</button>
</div>

<div id="panel-reviews" class="tab-panel active">
<div class="stats-strip">
  {review_stats_html}
</div>

<div class="toolbar">
  <div class="toolbar-title">PR reviews — sorted by most recent</div>
  <button class="filter-btn active" onclick="setFilter('verdict','all',this)">All</button>
  <button class="filter-btn" onclick="setFilter('verdict','approve',this)">✅ Approved</button>
  <button class="filter-btn" onclick="setFilter('verdict','block',this)">❌ Needs Changes</button>
  <button class="filter-btn" onclick="setFilter('verdict','comment',this)">💬 Needs Attention</button>
  <button class="filter-btn" onclick="setFilter('verdict','crit',this)">🔴 Critical</button>
  <button class="filter-btn" onclick="setFilter('verdict','high',this)">🟠 High</button>
  <div class="filter-sep"></div>
  <button class="filter-btn" onclick="setFilter('status','open',this)">🔵 Open</button>
  <button class="filter-btn" onclick="setFilter('status','merged',this)">🟢 Merged</button>
  <button class="filter-btn" onclick="setFilter('status','closed',this)">🟤 Closed</button>
  <div class="filter-sep"></div>
  <button class="filter-btn" onclick="setFilter('date','today',this)">Today</button>
  <button class="filter-btn" onclick="setFilter('date','week',this)">This Week</button>
  <button class="filter-btn" onclick="setFilter('date','month',this)">This Month</button>
</div>

<div class="grid" id="grid-reviews">
  {cards_html}
</div>
</div>

<div id="panel-evaluations" class="tab-panel">
<div class="stats-strip">
  {eval_stats_html}
</div>

<div class="toolbar">
  <div class="toolbar-title">Repo evaluations — sorted by most recent</div>
  <button class="filter-btn" onclick="setEvalFilter('risk','critical',this)">🔴 Critical</button>
  <button class="filter-btn" onclick="setEvalFilter('risk','high',this)">🟠 High</button>
  <button class="filter-btn" onclick="setEvalFilter('risk','all',this)">All</button>
</div>

<div class="grid" id="grid-evaluations">
  {eval_cards_html}
</div>
</div>

<script>
var _runState = document.getElementById('run-state');
var _runButton = document.getElementById('run-button');
var _evaluateButton = document.getElementById('evaluate-button');
var _feedbackButton = document.getElementById('feedback-button');
var _currentRun = null;
var _isLive = location.protocol === 'http:' || location.protocol === 'https:';
function apiUrl(path) {{
  return path;
}}
function liveError(error) {{
  if (!_isLive) {{
    return 'Open Cockpit at http://127.0.0.1:8765 with `eagleeye cockpit --open`. This saved HTML file cannot call the live APIs.';
  }}
  var message = (error && error.message) || '';
  if (/Failed to fetch|NetworkError|Load failed/i.test(message)) {{
    return 'Could not reach the Cockpit server. Keep `eagleeye cockpit` running and reload this page.';
  }}
  return message || 'Request failed';
}}
function showRun(run) {{
  _currentRun = run;
  if (!run) {{
    _runState.textContent = 'Ready to launch a PR review or repository evaluation.';
    _runState.dataset.status = '';
    _runButton.disabled = false;
    _evaluateButton.disabled = false;
    _feedbackButton.style.display = 'none';
    return;
  }}
  var label = run.owner + '/' + run.repo;
  if (run.kind === 'review') label += ' #' + run.pr_number;
  label += ' — ' + (run.kind || 'review') + ' ' + run.status;
  if (run.duration_seconds !== undefined) label += ' (' + run.duration_seconds + 's)';
  if (run.error) label += ': ' + run.error;
  _runState.textContent = label;
  if (run.status === 'completed' && run.artifacts) {{
    var artifactUrl = run.artifacts.html || run.artifacts.markdown;
    if (artifactUrl) {{
      var link = document.createElement('a');
      link.href = artifactUrl;
      link.target = '_blank';
      link.className = 'open-btn';
      link.textContent = 'Open report';
      _runState.appendChild(document.createTextNode(' '));
      _runState.appendChild(link);
    }}
  }}
  _runState.dataset.status = run.status;
  var active = run.status === 'queued' || run.status === 'running';
  _runButton.disabled = active;
  _evaluateButton.disabled = active;
  _feedbackButton.style.display = run.status === 'completed' ? '' : 'none';
}}
function startReview(event) {{
  event.preventDefault();
  _runButton.disabled = true;
  fetch(apiUrl('/run'), {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      owner: document.getElementById('run-owner').value.trim(),
      repo: document.getElementById('run-repo').value.trim(),
      pr_number: parseInt(document.getElementById('run-pr').value)
    }})
  }}).then(function(response) {{
    return response.json().then(function(body) {{
      if (!response.ok) throw new Error(body.error || 'Could not start review');
      showRun(body.run);
    }});
  }}).catch(function(error) {{
    _runState.textContent = liveError(error);
    _runState.dataset.status = 'failed';
    _runButton.disabled = false;
  }});
}}
function startEvaluation(event) {{
  event.preventDefault();
  _evaluateButton.disabled = true;
  fetch(apiUrl('/evaluate'), {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      owner: document.getElementById('eval-owner').value.trim(),
      repo: document.getElementById('eval-repo').value.trim(),
      branch: document.getElementById('eval-branch').value.trim(),
      path: document.getElementById('eval-path').value.trim(),
      quick: document.getElementById('eval-quick').checked,
      no_llm: document.getElementById('eval-no-llm').checked,
      include_data_dirs: document.getElementById('eval-data').checked
    }})
  }}).then(function(response) {{
    return response.json().then(function(body) {{
      if (!response.ok) throw new Error(body.error || 'Could not start evaluation');
      showRun(body.run);
    }});
  }}).catch(function(error) {{
    _runState.textContent = liveError(error);
    _runState.dataset.status = 'failed';
    _evaluateButton.disabled = false;
  }});
}}
function refreshForms() {{
  document.getElementById('run-form').reset();
  document.getElementById('evaluate-form').reset();
  var search = document.querySelector('.search-input');
  if (search) {{
    search.value = '';
    doSearch('');
  }}
  _feedbackButton.textContent = 'Record feedback';
  _feedbackButton.disabled = false;
  var busy = _currentRun && (_currentRun.status === 'queued' || _currentRun.status === 'running');
  if (!busy) showRun(null);
}}
function rerunReview(owner, repo, prNumber) {{
  document.getElementById('run-owner').value = owner;
  document.getElementById('run-repo').value = repo;
  document.getElementById('run-pr').value = prNumber;
  document.getElementById('run-form').requestSubmit();
  window.scrollTo({{top: 0, behavior: 'smooth'}});
}}
function rerunEvaluation(repoSlug, branch, scopedPath) {{
  var parts = (repoSlug || '').split('/');
  document.getElementById('eval-owner').value = parts.shift() || '';
  document.getElementById('eval-repo').value = parts.join('/');
  document.getElementById('eval-branch').value = branch || '';
  document.getElementById('eval-path').value = scopedPath || '';
  document.getElementById('evaluate-form').requestSubmit();
  window.scrollTo({{top: 0, behavior: 'smooth'}});
}}
function refreshMetrics() {{
  fetch(apiUrl('/metrics')).then(function(response) {{ return response.json(); }}).then(function(metrics) {{
    document.getElementById('pilot-metrics').textContent =
      metrics.runs + ' pilot runs · ' +
      Math.round(metrics.failure_rate * 100) + '% failures · ' +
      metrics.average_latency_seconds + 's avg · $' +
      metrics.total_cost_usd.toFixed(4) + ' · ' +
      metrics.false_positives_reported + ' false positives';
  }}).catch(function() {{}});
}}
function recordFeedback() {{
  if (!_currentRun) return;
  var count = window.prompt('How many findings were false positives?', '0');
  if (count === null) return;
  var notes = window.prompt('Optional feedback notes', '') || '';
  fetch(apiUrl('/feedback'), {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{run_id: _currentRun.id, false_positives: parseInt(count), notes: notes}})
  }}).then(function(response) {{
    if (!response.ok) throw new Error();
    _feedbackButton.textContent = 'Feedback recorded';
    _feedbackButton.disabled = true;
    refreshMetrics();
  }}).catch(function() {{ _runState.textContent = 'Could not record feedback.'; }});
}}
fetch(apiUrl('/status')).then(function(response) {{
  if (response.ok) return response.json();
  throw new Error();
}}).then(function(body) {{ showRun(body.current); }}).catch(function() {{
  _runState.textContent = 'Static Cockpit — run `eagleeye cockpit --open` and use http://127.0.0.1:8765.';
}});
if (_isLive && window.EventSource) {{
  var events = new EventSource(apiUrl('/events'));
  events.onmessage = function(message) {{
    var event = JSON.parse(message.data);
    if (event.type === 'run_status') {{
      if (_currentRun && event.run.updated_at < (_currentRun.updated_at || 0)) return;
      showRun(event.run);
      if (event.status === 'completed') refreshMetrics();
    }}
  }};
}}
if (_isLive) refreshMetrics();
document.addEventListener('click', function(event) {{
  var reviewBtn = event.target.closest('.rerun-review');
  if (reviewBtn) {{
    rerunReview(reviewBtn.dataset.owner, reviewBtn.dataset.repo, parseInt(reviewBtn.dataset.pr, 10));
    return;
  }}
  var evalBtn = event.target.closest('.rerun-evaluation');
  if (evalBtn) {{
    rerunEvaluation(evalBtn.dataset.repo, evalBtn.dataset.branch || '', evalBtn.dataset.path || '');
  }}
}});

function switchTab(name, btn) {{
  document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
  btn.classList.add('active');
  document.querySelectorAll('.tab-panel').forEach(function(p) {{ p.classList.remove('active'); }});
  document.getElementById('panel-' + name).classList.add('active');
}}

var _evalRisk = 'all';
function setEvalFilter(type, val, btn) {{
  document.querySelectorAll('#panel-evaluations .filter-btn').forEach(function(b) {{ b.classList.remove('active'); }});
  btn.classList.add('active');
  _evalRisk = val;
  applyEvalFilters();
}}
function applyEvalFilters() {{
  document.querySelectorAll('#grid-evaluations .eval-card').forEach(function(card) {{
    if (_evalRisk === 'all') {{ card.classList.remove('hidden'); return; }}
    if ((card.dataset.risk || '') === _evalRisk) card.classList.remove('hidden');
    else card.classList.add('hidden');
  }});
}}
</script>

<script>
// ── Live relative time (updates every minute) ──────────────────────────────
function timeAgo(ts) {{
  var secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 5)    return 'just now';
  if (secs < 60)   return secs + 's ago';
  if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
  if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
  var days = Math.floor(secs / 86400);
  return days === 1 ? 'yesterday' : days + 'd ago';
}}
function updateTimes() {{
  document.querySelectorAll('.time-ago[data-ts]').forEach(function(el) {{
    el.textContent = timeAgo(parseInt(el.dataset.ts));
  }});
}}
updateTimes();
setInterval(updateTimes, 60000);

// ── Filtering (verdict, status, date range) ───────────────────────────────
var _activeVerdict = 'all';
var _activeStatus  = '';
var _activeDate    = '';
var _searchQ       = '';

var _dateSeconds = {{ today: 86400, week: 604800, month: 2592000 }};

function updateStats() {{
  var visible = Array.from(document.querySelectorAll('.pr-card:not(.hidden)'));
  var total    = visible.length;
  var approved = visible.filter(function(c) {{ return c.dataset.verdict === 'approve'; }}).length;
  var blocked  = visible.filter(function(c) {{ return c.dataset.verdict === 'request_changes'; }}).length;
  var comment  = visible.filter(function(c) {{ return c.dataset.verdict === 'comment'; }}).length;
  var critical = visible.filter(function(c) {{ return c.dataset.risk === 'critical' || c.dataset.risk === 'high'; }}).length;
  var cost     = visible.reduce(function(s, c) {{ return s + parseFloat(c.dataset.cost || 0); }}, 0);

  document.getElementById('stat-total').textContent    = total;
  document.getElementById('stat-approved').textContent = approved;
  document.getElementById('stat-blocked').textContent  = blocked;
  document.getElementById('stat-comment').textContent  = comment;
  document.getElementById('stat-critical').textContent = critical;
  document.getElementById('stat-cost').textContent     = cost > 0 ? '$' + cost.toFixed(2) : '—';
}}

function applyFilters() {{
  var now = Math.floor(Date.now() / 1000);
  document.querySelectorAll('#grid-reviews .pr-card').forEach(function(card) {{
    var text = card.textContent.toLowerCase();

    if (_searchQ && !text.includes(_searchQ)) {{ card.classList.add('hidden'); return; }}

    if (_activeVerdict !== 'all') {{
      var match = card.classList.contains('risk-' + _activeVerdict) ||
                  card.querySelector('.v-' + _activeVerdict);
      if (!match) {{ card.classList.add('hidden'); return; }}
    }}

    if (_activeStatus) {{
      if ((card.dataset.status || '').toLowerCase() !== _activeStatus) {{
        card.classList.add('hidden'); return;
      }}
    }}

    if (_activeDate) {{
      var ts    = parseInt(card.dataset.ts || '0');
      var limit = _dateSeconds[_activeDate] || 0;
      if (now - ts > limit) {{ card.classList.add('hidden'); return; }}
    }}

    card.classList.remove('hidden');
  }});
  updateStats();
}}

function setFilter(type, val, btn) {{
  // Deactivate same-group buttons
  var groups = {{ verdict: [0,1,2,3,4,5], status: [6,7,8], date: [9,10,11] }};
  document.querySelectorAll('.filter-btn').forEach(function(b) {{
    if (b === btn) return;
    var sameGroup = false;
    if (type === 'verdict' && ['all','approve','block','comment','crit','high'].some(function(v) {{ return b.textContent.includes(v.charAt(0).toUpperCase()+v.slice(1)) || b.onclick.toString().includes("'"+v+"'"); }})) sameGroup = true;
    if (type === 'status'  && b.onclick.toString().includes("'status'")) sameGroup = true;
    if (type === 'date'    && b.onclick.toString().includes("'date'"))   sameGroup = true;
    if (sameGroup) b.classList.remove('active');
  }});
  btn.classList.toggle('active');
  var isActive = btn.classList.contains('active');

  if (type === 'verdict') _activeVerdict = isActive ? val : 'all';
  if (type === 'status')  _activeStatus  = isActive ? val : '';
  if (type === 'date')    _activeDate    = isActive ? val : '';

  applyFilters();
}}

function doSearch(q) {{
  _searchQ = q.toLowerCase();
  applyFilters();
  document.querySelectorAll('#grid-evaluations .eval-card').forEach(function(card) {{
    var text = card.textContent.toLowerCase();
    if (_searchQ && !text.includes(_searchQ)) card.classList.add('hidden');
    else if (_evalRisk === 'all' || (card.dataset.risk || '') === _evalRisk) card.classList.remove('hidden');
  }});
}}
</script>

</body>
</html>"""

    out = reviews_root() / "index.html"
    out.write_text(html, encoding="utf-8")
    return out
