"""Convert EagleEye markdown reviews to concise styled HTML."""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

from ...core.paths import reviews_root

REVIEWS_DIR = reviews_root()

_RISK_BORDER = {
    "CRITICAL": "#ff4444",
    "HIGH":     "#ff8800",
    "MEDIUM":   "#ffcc00",
    "LOW":      "#44aaff",
}

# EagleEye design system (from eagleeye-diagrams/rules.txt)
_COLORS = {
    "bg_dark":    "#0b1d2e",      # dark navy (page background)
    "bg_light":   "#0f2233",      # slightly lighter navy (containers)
    "bg_teal":    "#1a3a2a",      # dark teal green (secondary fill)
    "accent":     "#b3ff47",      # lime green (borders, highlights)
    "text":       "#ffffff",      # white (text)
}

_CSS = """
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg:     #0b1d2e;
      --panel:  #0f2233;
      --node:   #1a3a2a;
      --accent: #b3ff47;
      --text:   #ffffff;
      --muted:  #7fafc0;
      --border: rgba(179,255,71,0.22);
      --accent-subtle: rgba(179,255,71,0.08);
      --accent-light: rgba(179,255,71,0.15);
      --crit:   #ff4444;
      --high:   #ff8800;
      --med:    #ffcc00;
      --low:    #44aaff;
      --info:   #aaaaaa;
    }
    body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; font-size: 14.5px; line-height: 1.65; padding: 40px 24px 80px; }
    .page { max-width: 900px; margin: 0 auto; }

    .hero { background: var(--panel); border-radius: 12px; padding: 28px 36px 22px; margin-bottom: 28px; border: 1px solid var(--accent-light); }
    .hero-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 14px; flex-wrap: wrap; }
    .hero-eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; color: var(--accent); margin-bottom: 6px; opacity: 0.9; }
    .hero h1 { font-size: 19px; font-weight: 800; line-height: 1.3; }
    .pr-link { display: inline-flex; align-items: center; gap: 6px; background: rgba(255,255,255,0.06); border: 1px solid var(--border); border-radius: 8px; padding: 7px 14px; font-size: 12.5px; color: var(--text); text-decoration: none; white-space: nowrap; flex-shrink: 0; }
    .pr-link:hover { background: rgba(255,255,255,0.10); border-color: var(--accent); }
    .meta-row { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12.5px; color: var(--muted); align-items: center; }
    .meta-row strong { color: var(--text); }

    .badge { font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 20px; letter-spacing: 0.05em; white-space: nowrap; border: 1px solid; }
    .badge-critical { background: rgba(255,68,68,0.12);  border-color: var(--crit); color: var(--crit); }
    .badge-high     { background: rgba(255,136,0,0.12);  border-color: var(--high); color: var(--high); }
    .badge-medium   { background: rgba(255,204,0,0.10);  border-color: var(--med);  color: var(--med); }
    .badge-low      { background: rgba(68,170,255,0.10); border-color: var(--low);  color: var(--low); }
    .badge-info     { background: rgba(170,170,170,0.10);border-color: var(--info); color: var(--info); }

    .verdict { display: inline-flex; align-items: center; font-weight: 700; font-size: 12.5px; padding: 4px 12px; border-radius: 20px; }
    .verdict-critical { background: rgba(255,68,68,0.12); border: 1px solid var(--crit); color: var(--crit); }
    .verdict-high     { background: rgba(255,136,0,0.12);  border: 1px solid var(--high); color: var(--high); }
    .verdict-medium   { background: rgba(255,204,0,0.10);  border: 1px solid var(--med);  color: var(--med); }
    .verdict-low      { background: rgba(68,170,255,0.10); border: 1px solid var(--low);  color: var(--low); }

    section { margin-bottom: 24px; }
    .section-title { font-size: 11.5px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); margin-bottom: 12px; padding-bottom: 8px; border-bottom: 2px solid var(--accent-subtle); }

    .card { background: var(--panel); border: 1px solid var(--border); border-top: 2px solid var(--accent-subtle); border-radius: 10px; padding: 18px 22px; font-size: 13.5px; color: rgba(255,255,255,0.82); }

    .blocker-callout { background: rgba(255,68,68,0.06); border: 1px solid rgba(255,68,68,0.3); border-radius: 9px; padding: 12px 18px; margin-bottom: 24px; }
    .blocker-label { font-size: 11px; font-weight: 700; color: var(--crit); text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 7px; }
    .blocker-callout ul { margin: 0; padding-left: 18px; }
    .blocker-callout li { font-size: 13px; color: rgba(255,255,255,0.80); padding: 2px 0; }

    .finding-card { border-radius: 9px; padding: 14px 18px; margin-bottom: 10px; border: 1px solid var(--border); background: var(--panel); border-left: 2px solid var(--accent-subtle); }
    .finding-card.sev-critical { border-left: 5px solid var(--crit); background: rgba(255,68,68,0.04); }
    .finding-card.sev-high     { border-left: 4px solid var(--high); background: rgba(255,136,0,0.03); }
    .finding-card.sev-medium   { border-left: 3px solid var(--med); background: rgba(255,204,0,0.02); }
    .finding-card.sev-low      { border-left: 2px solid var(--low); }
    .finding-card.sev-info     { border-left: 2px solid var(--info); }
    .fc-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
    .fc-file { background: rgba(0,0,0,0.3); font-family: 'Courier New', monospace; font-size: 11.5px; color: var(--accent); padding: 2px 8px; border-radius: 4px; text-decoration: none; border: 1px solid rgba(179,255,71,0.2); }
    .fc-file:hover { border-color: var(--accent); background: rgba(179,255,71,0.1); }
    .fc-desc { font-size: 13px; color: rgba(255,255,255,0.78); line-height: 1.55; }
    .fc-more { margin-top: 4px; border: none; border-radius: 6px; display: block; }
    .fc-more > summary { font-size: 11.5px; color: var(--muted); cursor: pointer; list-style: none; padding: 2px 0; }
    .fc-more > summary:hover { color: var(--accent); }
    .fc-more > summary::marker, .fc-more > summary::-webkit-details-marker { display: none; }
    .fc-more[open] > summary { color: var(--accent); }
    .fc-more-text { font-size: 13px; color: rgba(255,255,255,0.78); line-height: 1.55; margin-top: 4px; }
    .fc-tip { margin-top: 10px; border: 1px solid rgba(179,255,71,0.18); border-radius: 7px; }
    .fc-tip > summary { padding: 7px 14px; font-size: 11.5px; font-weight: 600; color: var(--accent); cursor: pointer; list-style: none; display: flex; align-items: center; gap: 6px; border-radius: 7px; }
    .fc-tip > summary::before { content: "▶"; font-size: 9px; opacity: 0.6; }
    .fc-tip[open] > summary::before { content: "▼"; }
    .fc-tip > summary:hover { background: rgba(179,255,71,0.05); }
    .fc-tip-text { padding: 0 14px 10px; font-size: 12.5px; color: rgba(255,255,255,0.70); }
    .fc-tip pre { padding: 0 14px 10px; }
    pre { margin: 8px 0 0; overflow-x: auto; }
    pre code { display: block; background: rgba(0,0,0,0.45); border-radius: 6px; padding: 10px 14px; font-family: 'Courier New', monospace; font-size: 12px; color: rgba(255,255,255,0.82); line-height: 1.5; white-space: pre; }
    .edp-tree { margin: 0; overflow-x: auto; border-radius: 10px; border: 1px solid var(--border); }
    .edp-tree code { background: var(--panel); border-radius: 10px; padding: 16px 20px; font-family: 'Courier New', monospace; font-size: 12.5px; color: rgba(255,255,255,0.85); line-height: 1.9; white-space: pre; }

    .positive-item { display: flex; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; color: rgba(255,255,255,0.78); align-items: flex-start; }
    .positive-item:last-child { border-bottom: none; }
    .check { color: var(--accent); font-size: 15px; flex-shrink: 0; margin-top: 1px; }

    .table-wrap { overflow-x: auto; border-radius: 10px; border: 1px solid var(--border); }
    table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
    thead tr { background: var(--node); border-bottom: 2px solid var(--accent-subtle); }
    th { padding: 10px 14px; text-align: left; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.07em; color: var(--accent); white-space: nowrap; }
    td { padding: 11px 14px; border-top: 1px solid rgba(179,255,71,0.05); color: rgba(255,255,255,0.78); vertical-align: top; }
    tbody tr:nth-child(odd) { background: rgba(179,255,71,0.02); }
    tbody tr:nth-child(even) { background: transparent; }
    tbody tr:hover { background: rgba(179,255,71,0.05); }
    .section-gap { font-size: 13px; color: var(--muted); margin-bottom: 12px; }

    code { background: rgba(0,0,0,0.3); font-family: 'Courier New', monospace; font-size: 12px; padding: 1px 5px; border-radius: 3px; color: var(--accent); }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }

    .footer { margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--border); font-size: 11.5px; color: var(--muted); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }

    .lineage-tree { font-family: monospace; font-size: 13px; line-height: 1.7; padding: 8px 0; }
    .lineage-tree details { margin-left: 20px; }
    .lineage-tree details[open] > summary.lt-node::before { content: "▾ "; }
    summary.lt-node { cursor: pointer; color: var(--accent); list-style: none; padding: 2px 0; font-weight: 500; }
    summary.lt-node::before { content: "▸ "; font-size: 10px; font-weight: 600; margin-right: 4px; opacity: 0.8; transition: opacity 0.2s; }
    summary.lt-node:hover { opacity: 1; }
    summary.lt-node:hover::before { opacity: 1; }
    .lt-leaf { margin-left: 20px; color: var(--muted); padding: 1px 0; }
    .lt-leaf::before { content: "· "; opacity: 0.4; margin-right: 4px; }
    .lt-children { border-left: 1px solid var(--accent-subtle); margin-left: 6px; padding-left: 8px; }
    .lt-more { margin-left: 0; }
    .lt-more-toggle { cursor: pointer; list-style: none; font-size: 11.5px; color: var(--accent); opacity: 0.7; padding: 3px 0; font-weight: 500; }
    .lt-more-toggle:hover { opacity: 1; }
    .lt-more-toggle::before { content: "+ "; font-size: 10px; margin-right: 4px; }
    .lt-more-note { font-size: 11.5px; color: var(--muted); font-style: italic; padding: 4px 0; }
"""


# ── Parsing ────────────────────────────────────────────────────────────────────

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not m:
        return {}, content
    fm: dict = {}
    for line in m.group(1).splitlines():
        key, _, val = line.partition(":")
        if key.strip():
            fm[key.strip()] = val.strip()
    return fm, content[m.end():]


def _extract_verdict_risk(text: str) -> tuple[str, str]:
    m = re.search(
        r"\*\*Review:\*\*\s*(.+?)(?:\s*&nbsp;·&nbsp;\s*|\s*·\s*)\s*\*\*Risk:\*\*\s*`([^`]+)`",
        text,
    )
    if m:
        verdict = m.group(1).strip()
        risk = re.sub(r"[^\w\s]", "", m.group(2)).strip().upper()
        return verdict, risk
    return "Let's revisit ❌", "UNKNOWN"


def _parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_body: list[str] = []
    in_fence = False

    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^### (.+)$", line):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_body).strip()
            current_heading = re.match(r"^### (.+)$", line).group(1).strip()
            current_body = []
        else:
            current_body.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_body).strip()

    return sections


def _parse_bullet_list(text: str) -> list[str]:
    return [line.strip()[2:] for line in text.splitlines() if line.strip().startswith("- ")]


def _parse_code_block(text: str) -> tuple[str, str]:
    """Return (pre_text, code_content) if a fenced code block is present, else ('', '')."""
    m = re.search(r"```[a-z]*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return text[: m.start()].strip(), m.group(1)
    return "", ""


def _parse_markdown_table(text: str) -> tuple[str, list[str], list[list[str]]]:
    lines = text.splitlines()
    table_lines = [line.strip() for line in lines if line.strip().startswith("|")]
    pre = text[: text.find("|")].strip() if "|" in text else ""
    if len(table_lines) < 2:
        return pre, [], []

    def _split_row(row: str) -> list[str]:
        return [c.strip() for c in row.strip("|").split("|")]

    headers = _split_row(table_lines[0])
    rows = [_split_row(line) for line in table_lines[2:]]
    return pre, headers, rows


def _parse_remediation(text: str) -> list[dict]:
    """Parse Remediation Details section, capturing descriptions, tips, and code blocks."""
    items: list[dict] = []
    blocks = re.split(r"(?=^\*\*`[A-Z]+`\*\*)", text, flags=re.MULTILINE)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        hm = re.match(
            r"^\*\*`([A-Z]+)`\*\*\s*`([^`]+)`(?:\s*\(lines?\s*([^)]+)\))?", block
        )
        if not hm:
            continue
        severity = hm.group(1)
        file_path = hm.group(2)
        line_ref = hm.group(3).strip() if hm.group(3) else None
        rest = block[hm.end():].strip()

        # Extract fenced code block before anything else
        code_m = re.search(r"```\w*\n(.*?)```", rest, re.DOTALL)
        code = code_m.group(1).rstrip() if code_m else None
        rest_no_code = re.sub(r"```\w*\n.*?```", "", rest, flags=re.DOTALL).strip()

        # Extract tip line (> 💡 ...)
        tip_m = re.search(r"^>\s*💡?\s*(.+?)$", rest_no_code, re.MULTILINE)
        if tip_m:
            tip = tip_m.group(1).strip()
            description = rest_no_code[: tip_m.start()].strip()
        else:
            tip = None
            description = rest_no_code

        items.append({
            "severity": severity,
            "file_path": file_path,
            "line_ref": line_ref,
            "description": description,
            "tip": tip,
            "code": code,
        })
    return items


def _parse_misc_issues(text: str) -> list[dict]:
    """Parse Misc Issues section (low/info severity)."""
    items: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = re.match(
            r"^-\s+\*\*`([A-Z]+)`\*\*\s+`([^`]+)`(?::([0-9][0-9\-]*))?(?:\s+—\s+(.+))?",
            line.strip(),
        )
        if m:
            current = {
                "severity": m.group(1),
                "file_path": m.group(2),
                "line_ref": m.group(3),
                "description": (m.group(4) or "").strip(),
                "tip": None,
                "code": None,
            }
            items.append(current)
        elif current and re.match(r"^>\s*💡?\s*", line.strip()):
            current["tip"] = re.sub(r"^>\s*💡?\s*", "", line.strip())
    return items


# ── Formatters ─────────────────────────────────────────────────────────────────

def _fmt(text: str) -> str:
    text = _html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def _render_lineage_tree(text: str) -> str:
    """Convert indented text tree to collapsible <details>/<summary> HTML.

    Handles the EDP flat-pair format where the same node appears as both
    a root (with a suffix like [Added]) and a child (without the suffix):

        RDS.TABLE_A  [Added]
          └── RDS.TABLE_B

        RDS.TABLE_B  [Added]
          └── ODS.VIEW_B

    Normalises labels to build a graph, finds true roots (nodes never
    referenced as a child), then renders a single nested tree from each root.
    """
    import re as _re
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    _TREE_CHARS = _re.compile(r'^[\s│├└─→✓~!\s]+')
    _SUFFIX_RE = _re.compile(r'\s*\[(?:Added|Modified|Deleted|Renamed|Altered|Dropped)\].*$', _re.IGNORECASE)

    def _indent(line: str) -> int:
        return len(line) - len(line.lstrip())

    def _label(line: str) -> str:
        return _TREE_CHARS.sub("", line).strip()

    def _key(label: str) -> str:
        return _SUFFIX_RE.sub("", label).strip().upper()

    # Build adjacency graph: normalized key → {display label, children list}
    nodes: dict[str, dict] = {}
    child_keys: set[str] = set()
    parent_order: list[str] = []

    i = 0
    while i < len(lines):
        if _indent(lines[i]) == 0:
            parent_lbl = _label(lines[i])
            parent_key = _key(parent_lbl)
            if parent_key not in nodes:
                nodes[parent_key] = {"label": parent_lbl, "children": []}
                parent_order.append(parent_key)
            j = i + 1
            while j < len(lines) and _indent(lines[j]) > 0:
                child_lbl = _label(lines[j])
                child_key = _key(child_lbl)
                child_keys.add(child_key)
                if child_key not in nodes:
                    nodes[child_key] = {"label": child_lbl, "children": []}
                if child_key not in nodes[parent_key]["children"]:
                    nodes[parent_key]["children"].append(child_key)
                j += 1
            i = j
        else:
            i += 1

    # True roots: appear as parents but never as children
    roots = [k for k in parent_order if k not in child_keys]
    if not roots:
        roots = parent_order  # fallback — show everything

    _INLINE_LIMIT = 5  # children shown immediately; extras behind "Show N more"

    import re as _re2
    _MORE_RE = _re2.compile(
        r'^(.*?)\s*[\(\+]+(?:and\s+)?(\d+)\s+more[^\)]*\)?$', _re2.IGNORECASE
    )

    def _render_node(key: str, depth: int, visited: frozenset) -> str:
        if key in visited:
            label = _html.escape(nodes[key]["label"]) if key in nodes else _html.escape(key)
            return f'<div class="lt-leaf lt-cycle">{label} ↩</div>'
        node = nodes.get(key, {"label": key, "children": []})
        raw_label = node["label"]
        # Detect leaf labels like "FOO_BAR (+9 more)" or "BAZ (and 9 more consumers...)"
        # and convert them into a real expandable placeholder instead of dead text
        more_m = _MORE_RE.match(raw_label) if not node["children"] else None
        if more_m:
            base = _html.escape(more_m.group(1).strip())
            count = int(more_m.group(2))
            return (
                f'<div class="lt-leaf">{base}</div>'
                f'<details class="lt-more"><summary class="lt-more-toggle">'
                f'Show {count} more consumers…</summary>'
                f'<div class="lt-children lt-more-note">'
                f'Full consumer list not available — re-run the review to fetch all {count} names.'
                f'</div></details>'
            )
        label = _html.escape(raw_label)
        kids = node["children"]
        if kids:
            open_attr = " open" if depth == 0 else ""
            shown = kids[:_INLINE_LIMIT]
            hidden = kids[_INLINE_LIMIT:]
            shown_html = "".join(
                _render_node(c, depth + 1, visited | {key}) for c in shown
            )
            more_html = ""
            if hidden:
                hidden_html = "".join(
                    _render_node(c, depth + 1, visited | {key}) for c in hidden
                )
                more_html = (
                    f'<details class="lt-more"><summary class="lt-more-toggle">'
                    f'Show {len(hidden)} more…</summary>'
                    f'<div class="lt-children">{hidden_html}</div></details>'
                )
            return (
                f'<details{open_attr}><summary class="lt-node">{label}</summary>'
                f'<div class="lt-children">{shown_html}{more_html}</div></details>'
            )
        return f'<div class="lt-leaf">{label}</div>'

    body = "".join(_render_node(r, 0, frozenset()) for r in roots)
    return f'<div class="lineage-tree">{body}</div>'


def _badge(severity: str) -> str:
    return f'<span class="badge badge-{severity.lower()}">{severity}</span>'


def _gh_link(repo: str, pr: str, file_path: str, line_ref: str | None = None) -> str:
    if file_path:
        url = f"https://github.com/{repo}/blob/main/{file_path}"
        if line_ref:
            parts = str(line_ref).split("-")
            url += f"#L{parts[0]}"
            if len(parts) == 2:
                url += f"-L{parts[1]}"
    else:
        url = f"https://github.com/{repo}/pull/{pr}/files"
    return url


# ── HTML builder ───────────────────────────────────────────────────────────────

_PR_STATUS_STYLE = {
    "open":   ("color:#44aaff", "OPEN"),
    "closed": ("color:#ff8800", "CLOSED"),
    "merged": ("color:#b3ff47", "MERGED"),
}


def _render_schema_impact_html(result) -> str:
    """Render a SchemaImpactResult as a styled HTML panel. Returns '' if no changes."""
    if not result or not getattr(result, "changes", None):
        return ""

    _KIND_LABEL = {
        "sql_column": "SQL DDL col", "sql_table": "SQL DDL table",
        "alembic_column": "Alembic col", "alembic_table": "Alembic table",
        "sqlalchemy_column": "SQLAlchemy ORM", "django_field": "Django ORM",
        "pydantic_field": "Pydantic field", "typeddict_field": "TypedDict key",
        "dataclass_field": "Dataclass field",
    }
    _CHANGE_STYLE = {
        "removed":      ("#ff4444", "rgba(255,68,68,0.15)"),
        "type_changed": ("#ff8800", "rgba(255,136,0,0.15)"),
        "renamed":      ("#ffcc00", "rgba(255,204,0,0.15)"),
        "added":        ("#b3ff47", "rgba(179,255,71,0.15)"),
        "modified":     ("#44aaff", "rgba(68,170,255,0.15)"),
    }
    _CONSUMER_EMOJI = {
        "query": "🗄️", "orm": "🔗", "serializer": "📋",
        "handler": "🌐", "test": "🧪", "": "📄",
    }

    # Collect unique parent objects for the section header
    parents = list(dict.fromkeys(c.parent for c in result.changes if c.parent))

    # Compact row per change — div-based (avoids invalid details-inside-tbody)
    _ROW_STYLE = (
        "display:flex;align-items:center;gap:10px;padding:7px 16px;"
        "border-bottom:1px solid rgba(179,255,71,0.06);font-size:12.5px;flex-wrap:wrap"
    )

    def _make_row(c) -> str:
        color, bg = _CHANGE_STYLE.get(c.change_type, ("#aaaaaa", "rgba(170,170,170,0.15)"))
        badge = (
            f'<span style="background:{bg};color:{color};border:1px solid {color}40;'
            f'padding:1px 7px;border-radius:20px;font-size:10px;font-weight:700;flex-shrink:0">'
            f'{c.change_type}</span>'
        )
        col_type = (
            f'<span style="color:var(--muted);font-size:11px">{_html.escape(c.col_type)}</span>'
            if c.col_type else ""
        )
        parent = (
            f'<span style="color:var(--muted);font-family:monospace;font-size:11px;flex-shrink:0">'
            f'{_html.escape(c.parent)}</span>'
        ) if c.parent else ""
        file_link = (
            f'<a href="#" style="color:var(--accent);font-family:monospace;font-size:11px;'
            f'text-decoration:none;margin-left:auto;flex-shrink:0">'
            f'{_html.escape(c.file)}:{c.line}</a>'
        )
        return (
            f'<div style="{_ROW_STYLE}">'
            f'{badge}'
            f'<code style="flex-shrink:0">{_html.escape(c.name)}</code>'
            f'{col_type}'
            f'{parent}'
            f'{file_link}'
            f'</div>'
        )

    _INLINE = 4
    visible_html = "".join(_make_row(c) for c in result.changes[:_INLINE])
    extra = result.changes[_INLINE:]
    if extra:
        hidden_html = "".join(_make_row(c) for c in extra)
        visible_html += (
            f'<details><summary style="padding:7px 16px;cursor:pointer;color:var(--muted);'
            f'font-size:11.5px;list-style:none;border-bottom:1px solid rgba(179,255,71,0.06)">'
            f'Show {len(extra)} more change(s)\u2026'
            f'</summary>{hidden_html}</details>'
        )

    table_html = (
        f'<div style="border-top:1px solid rgba(179,255,71,0.1)">{visible_html}</div>'
    )

    # Downstream consumers — grouped by OBJECT (parent table), not by column
    consumers_html = ""
    if result.consumers:
        from collections import defaultdict as _dd
        obj_map: dict = _dd(list)   # {parent_object: [(col_name, consumer), ...]}
        for key, consumers in sorted(result.consumers.items()):
            # key = "PARENT.column" or just "column"
            if "." in key:
                parent_obj, col_name = key.rsplit(".", 1)
            else:
                parent_obj, col_name = "—", key
            for c in consumers:
                obj_map[parent_obj].append((col_name, c))

        obj_items = ""
        total_refs = sum(len(v) for v in obj_map.values())
        for obj, pairs in sorted(obj_map.items()):
            cols = list(dict.fromkeys(p[0] for p in pairs))
            cols_label = ", ".join(f"<code>{_html.escape(c)}</code>" for c in cols[:5])
            if len(cols) > 5:
                cols_label += f" <span style='color:var(--muted)'>+{len(cols)-5} more</span>"
            refs_html = "".join(
                f'<div style="font-size:12px;padding:2px 0">'
                f'{_CONSUMER_EMOJI.get(c.consumer_kind, "📄")} '
                f'<code>{_html.escape(c.file)}:{c.line}</code>'
                f' <span style="color:var(--muted);font-size:11px">[{_html.escape(col)}]</span>'
                f' — <code style="font-size:11px">{_html.escape(c.snippet[:70])}</code></div>'
                for col, c in pairs[:10]
            )
            more_str = (
                f'<div style="font-size:11px;color:var(--muted);font-style:italic">…and {len(pairs)-10} more</div>'
            ) if len(pairs) > 10 else ""
            obj_items += (
                f'<details style="margin-bottom:6px">'
                f'<summary style="cursor:pointer;color:var(--accent);font-size:13px;font-weight:600;padding:3px 0">'
                f'<code>{_html.escape(obj)}</code>'
                f' <span style="color:var(--muted);font-weight:400;font-size:11.5px">— {len(pairs)} ref(s) · {cols_label}</span>'
                f'</summary>'
                f'<div style="margin-left:16px;margin-top:4px">{refs_html}{more_str}</div>'
                f'</details>'
            )

        consumers_html = (
            f'<details style="margin:0">'
            f'<summary style="padding:10px 20px;cursor:pointer;font-size:12.5px;color:var(--muted);'
            f'border-top:1px solid var(--border)">'
            f'⚠️ Downstream impact — <strong style="color:var(--text)">{total_refs} reference(s)</strong>'
            f' across <strong style="color:var(--text)">{len(obj_map)} object(s)</strong> — click to expand'
            f'</summary>'
            f'<div style="padding:8px 20px 12px">{obj_items}'
            f'<div style="font-size:11.5px;color:var(--muted);margin-top:6px">'
            f'Removed/renamed elements cause runtime errors · type changes cause silent data corruption.'
            f'</div></div>'
            f'</details>'
        )

    n = len(result.changes)
    summary = f"<strong>{n} schema change{'s' if n != 1 else ''}</strong> across {result.files_analyzed} file(s)"

    if parents:
        shown = parents[:4]
        rest = parents[4:]
        objects_str = " · ".join(f"<code>{_html.escape(p)}</code>" for p in shown)
        if rest:
            objects_str += f" <span style='color:var(--muted);font-size:10px'>+{len(rest)} more</span>"
        section_title = f"Schema Changes &mdash; {objects_str}"
    else:
        section_title = "Schema Changes"

    return (
        '\n  <section>'
        f'\n    <div class="section-title">{section_title}</div>'
        '\n    <div class="card" style="padding:0;overflow:hidden">'
        f'\n      <div style="padding:14px 20px 8px;font-size:13px">{summary}</div>'
        f'\n      {table_html}'
        f'\n      {consumers_html}'
        '\n    </div>'
        '\n  </section>'
    )


def _build_html(fm: dict, verdict: str, risk: str, sections: dict, schema_impact=None) -> str:
    repo       = fm.get("repo", "")
    pr         = fm.get("pr", "")
    title      = fm.get("title", f"PR #{pr}")
    date       = fm.get("date", "")
    pr_url     = fm.get("url", f"https://github.com/{repo}/pull/{pr}")
    req_by     = fm.get("requested_by", "")
    pr_status  = fm.get("pr_status", "")
    tok_in     = fm.get("tokens_input", "")
    tok_out    = fm.get("tokens_output", "")
    cost_usd   = fm.get("cost_usd", "")

    border   = _RISK_BORDER.get(risk, "#b3ff47")
    risk_cls = risk.lower()

    # ── Hero
    meta = [
        f'<div class="verdict verdict-{risk_cls}">{verdict}</div>',
        f'<span class="badge badge-{risk_cls}">{risk} RISK</span>',
        f'<span><strong>Repo:</strong> <a href="https://github.com/{repo}" target="_blank" style="color:inherit">{repo}</a></span>',
    ]
    if pr_status:
        style, label = _PR_STATUS_STYLE.get(pr_status.lower(), ("color:var(--muted)", pr_status.upper()))
        meta.append(f'<span>Current Status: <span style="{style};font-weight:700">{label}</span></span>')
    if req_by:
        meta.append(f"<span><strong>By:</strong> @{req_by}</span>")
    if date:
        meta.append(f"<span><strong>Reviewed:</strong> {date}</span>")
    if tok_in and tok_out:
        total = int(tok_in) + int(tok_out)
        cost_str = f" · ${float(cost_usd):.4f}" if cost_usd else ""
        meta.append(f'<span style="color:var(--muted)">&#128202; {total:,} tokens ({tok_in} in / {tok_out} out{cost_str})</span>')

    hero = f"""
  <div class="hero" style="border:1.5px solid {border}">
    <div class="hero-top">
      <div>
        <div class="hero-eyebrow">EagleEye Code Review</div>
        <h1>PR #{pr} &middot; {_html.escape(title)}</h1>
      </div>
      <a href="{pr_url}" target="_blank" class="pr-link">View on GitHub &#8599;</a>
    </div>
    <div class="meta-row">{"".join(meta)}</div>
  </div>"""

    # ── Summary
    summary_html = ""
    if "Summary" in sections:
        summary_html = f"""
  <section>
    <div class="section-title">Summary</div>
    <div class="card">{_fmt(sections["Summary"])}</div>
  </section>"""

    # ── Blocking callout (compact strip, not a full section)
    blocker_html = ""
    block_key = next((k for k in sections if "Blocking" in k), None)
    if block_key:
        items = _parse_bullet_list(sections[block_key])
        if items:
            lis = "".join(f"<li>{_fmt(i)}</li>" for i in items)
            blocker_html = f"""
  <div class="blocker-callout">
    <span class="blocker-label">&#x26D4; Blocking Issues</span>
    <ul>{lis}</ul>
  </div>"""

    # ── Findings (merged from Remediation Details + Misc Issues)
    findings_html = ""
    rem_key  = next((k for k in sections if "Remediation" in k), None)
    misc_key = next((k for k in sections if "Misc" in k), None)

    all_findings: list[dict] = []
    if rem_key:
        all_findings = _parse_remediation(sections[rem_key])
    elif "Findings" in sections:
        # fallback: parse legacy Findings section without remediation detail
        for sev_m in re.finditer(r"^\*\*([A-Z]+)\*\*", sections["Findings"], re.MULTILINE):
            pass  # handled below via _parse_misc_issues-style fallback
        cur_sev = "MEDIUM"
        for line in sections["Findings"].splitlines():
            bm = re.match(r"^\*\*([A-Z]+)\*\*$", line.strip())
            if bm:
                cur_sev = bm.group(1)
                continue
            if line.strip().startswith("- "):
                item = line.strip()[2:]
                fm2 = re.search(r"—\s*`([^`]+)`(?::([0-9][0-9\-]*))?(\s*)$", item)
                fp = lr = None
                if fm2:
                    fp = fm2.group(1)
                    lr = fm2.group(2)
                    item = item[: fm2.start()].strip()
                all_findings.append({
                    "severity": cur_sev,
                    "file_path": fp or "",
                    "line_ref": lr,
                    "description": item,
                    "tip": None,
                    "code": None,
                })
    if misc_key:
        all_findings += _parse_misc_issues(sections[misc_key])

    if all_findings:
        cards = ""
        for item in all_findings:
            sev = item["severity"].lower()
            fp  = item.get("file_path") or ""
            lr  = item.get("line_ref")
            url = _gh_link(repo, pr, fp, lr) if fp else "#"
            label = _html.escape(fp + (f":{lr}" if lr else ""))

            # Suggestion — collapsible, hidden by default
            tip_block = ""
            if item.get("tip") or item.get("code"):
                tip_content = ""
                if item.get("tip"):
                    tip_content += f'<div class="fc-tip-text">{_fmt(item["tip"])}</div>'
                if item.get("code"):
                    tip_content += f'<pre><code>{_html.escape(item["code"])}</code></pre>'
                tip_block = f'<details class="fc-tip"><summary>&#128161; Suggestion</summary>{tip_content}</details>'

            # Description — truncate at ~160 chars if long, rest behind "more" toggle
            raw_desc = item["description"]
            if len(raw_desc) > 200:
                cut = raw_desc.rfind(" ", 0, 160)
                if cut < 80:
                    cut = 160
                head = _fmt(raw_desc[:cut])
                tail = _fmt(raw_desc[cut:].lstrip())
                desc_html = (
                    f'<p class="fc-desc">{head}\u2026</p>'
                    f'<details class="fc-more"><summary>Show full description</summary>'
                    f'<div class="fc-more-text">{tail}</div></details>'
                )
            else:
                desc_html = f'<p class="fc-desc">{_fmt(raw_desc)}</p>'

            cards += f"""
    <div class="finding-card sev-{sev}">
      <div class="fc-header">
        {_badge(item["severity"])}
        <a href="{url}" target="_blank" class="fc-file">{label}</a>
      </div>
      {desc_html}
      {tip_block}
    </div>"""

        findings_html = f"""
  <section>
    <div class="section-title">Findings</div>
    {cards}
  </section>"""

    # ── Impact sections (EDP tree / Feature Store table)
    impact_html = ""
    for key in sections:
        if not any(w in key for w in ("Impact", "EDP", "Feature Store", "Pipeline")):
            continue
        section_text = sections[key]

        # Tree (code block) takes priority — used for EDP lineage
        pre_text, code = _parse_code_block(section_text)
        if code:
            pre_p = f'<p class="section-gap">{_fmt(pre_text)}</p>' if pre_text else ""
            tree_html = _render_lineage_tree(code)
            content_html = (
                tree_html
                if tree_html
                else f'<pre class="edp-tree"><code>{_html.escape(code)}</code></pre>'
            )
            # Extract root object names for compact summary
            root_names = [
                ln.split()[0] for ln in code.splitlines()
                if ln and not ln[0].isspace() and ln.strip()
            ]
            if root_names:
                shown_names = " · ".join(f"<code>{_html.escape(n)}</code>" for n in root_names[:3])
                if len(root_names) > 3:
                    shown_names += f" <span style='color:var(--muted)'>+{len(root_names)-3} more</span>"
                summary_line = f"<strong>{len(root_names)} object(s)</strong> — {shown_names}"
            else:
                summary_line = "Lineage tree"
            impact_html += f"""
  <section>
    <div class="section-title">{key}</div>
    {pre_p}
    <details>
      <summary style="cursor:pointer;padding:10px 14px;background:var(--panel);border:1px solid var(--border);border-radius:9px;font-size:13px;color:var(--muted);list-style:none;display:flex;align-items:center;gap:8px">
        <span style="color:var(--accent);font-size:10px">▶</span>
        {summary_line} — <span style="font-size:12px">click to expand lineage</span>
      </summary>
      <div style="margin-top:8px">{content_html}</div>
    </details>
  </section>"""
            continue

        # Fall back to table (Feature Store and legacy EDP)
        pre, headers, rows = _parse_markdown_table(section_text)
        if not headers:
            continue
        pre_p = f'<p class="section-gap">{_fmt(pre)}</p>' if pre else ""
        ths = "".join(f"<th>{h}</th>" for h in headers)
        trs = "".join(
            "<tr>" + "".join(f"<td>{_fmt(c)}</td>" for c in row) + "</tr>"
            for row in rows
        )
        impact_html += f"""
  <section>
    <div class="section-title">{key}</div>
    {pre_p}
    <div class="table-wrap">
      <table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>
    </div>
  </section>"""

    # ── Positive Highlights
    positives_html = ""
    pos_key = next((k for k in sections if "Positive" in k), None)
    if pos_key:
        items = _parse_bullet_list(sections[pos_key])
        rows_html = "".join(
            f'<div class="positive-item"><span class="check">&#10003;</span><span>{_fmt(i)}</span></div>'
            for i in items
        )
        positives_html = f"""
  <section>
    <div class="section-title">Positive Highlights</div>
    <div class="card">{rows_html}</div>
  </section>"""

    schema_html = _render_schema_impact_html(schema_impact) if schema_impact else ""

    # ── Footer
    footer = f"""
  <div class="footer">
    <div>Generated by EagleEye powered by Claude &middot; {date}</div>
    <div><a href="{pr_url}" target="_blank">{repo} &mdash; PR #{pr}</a></div>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>EagleEye &mdash; PR #{pr} &middot; {_html.escape(title)}</title>
  <style>{_CSS}  </style>
</head>
<body>
<div class="page">
{hero}
{summary_html}
{blocker_html}
{schema_html}
{findings_html}
{impact_html}
{positives_html}
{footer}
</div>
</body>
</html>"""


# ── Public API ─────────────────────────────────────────────────────────────────

def process(
    md_path: Path,
    reviews_root: Path | None = None,
    output_root: Path | None = None,
    schema_impact=None,
) -> Path:
    """Convert a review markdown file to HTML. Returns the output path."""
    content = md_path.read_text(encoding="utf-8")
    fm, rest = _parse_frontmatter(content)
    verdict, risk = _extract_verdict_risk(rest)
    sections = _parse_sections(rest)
    html = _build_html(fm, verdict, risk, sections, schema_impact=schema_impact)

    if reviews_root and output_root:
        relative = md_path.relative_to(reviews_root)
        out = output_root / relative.with_suffix(".html")
    else:
        out = md_path.with_suffix(".html")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
