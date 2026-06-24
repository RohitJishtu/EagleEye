"""Feature store impact analysis.

Deterministically extracts feature store artifacts from a diff and maps
cross-file relationships before Claude sees any data. This gives the Feature
Agent a pre-computed brief instead of raw diff text to guess from.

Detects:
  - Feature group / feature table definitions changed
  - Feature column additions, removals, renames, type changes
  - Feature load job configs changed (Databricks YAML)
  - Model registration / training job configs changed
  - Feature references in training / inference scripts

Scans full file contents to map:
  - Which load jobs serve which feature groups
  - Which model jobs consume which feature groups
  - Feature columns referenced in training vs inference code
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional



@dataclass
class FeatureColumnChange:
    column_name: str
    change_type: str        # "added" | "removed" | "renamed" | "type_changed" | "modified"
    old_type: str = ""
    new_type: str = ""
    file: str = ""
    line: int = 0
    detail: str = ""


@dataclass
class FeatureJobChange:
    job_name: str
    job_kind: str           # "load" | "register" | "train" | "score" | "validate"
    change_type: str        # "added" | "modified" | "removed"
    feature_groups: list[str] = field(default_factory=list)  # feature groups this job touches
    file: str = ""
    detail: str = ""


@dataclass
class FeatureConsumer:
    """A place in the codebase that references a changed feature column or group."""
    file: str
    line: int
    snippet: str
    consumer_kind: str = ""  # "training" | "inference" | "validation" | "load" | "other"


@dataclass
class FeatureStoreExtract:
    column_changes: list[FeatureColumnChange] = field(default_factory=list)
    job_changes: list[FeatureJobChange] = field(default_factory=list)
    consumers: dict[str, list[FeatureConsumer]] = field(default_factory=dict)
    feature_groups_affected: list[str] = field(default_factory=list)
    files_analyzed: int = 0


# Patterns that identify feature store artifacts by file path
_LOAD_JOB_PATTERNS = [
    r"load[_\-].*feature",
    r"feature[_\-].*load",
    r"load[_\-].*metric",
    r"feature_load",
    r"load_feature",
]

_MODEL_JOB_PATTERNS = [
    r"register[_\-].*model",
    r"train[_\-].*model",
    r"score[_\-].*model",
    r"model[_\-].*register",
    r"model[_\-].*train",
]

_FEATURE_DEF_PATTERNS = [
    r"feature[_\-]group",
    r"featuregroup",
    r"feature[_\-]store",
    r"feature[_\-]definition",
    r"feature[_\-]schema",
    r"feature[_\-]config",
]

_TRAINING_SCRIPT_PATTERNS = [
    r"train[_\-]",
    r"[_\-]train",
    r"training",
    r"fit[_\-]model",
]

_INFERENCE_SCRIPT_PATTERNS = [
    r"infer",
    r"score[_\-]",
    r"predict",
    r"serving",
]

_VALIDATION_PATTERNS = [
    r"feature[_\-]valid",
    r"valid[_\-]feature",
    r"feature[_\-]check",
]


def _classify_file(path: str) -> str:
    """Return the role of a file in the feature store pipeline."""
    p = path.lower()
    name = Path(p).stem

    if any(re.search(pat, name) for pat in _LOAD_JOB_PATTERNS):
        return "load"
    if any(re.search(pat, name) for pat in _MODEL_JOB_PATTERNS):
        return "register"
    if any(re.search(pat, name) for pat in _FEATURE_DEF_PATTERNS):
        return "feature_def"
    if any(re.search(pat, name) for pat in _TRAINING_SCRIPT_PATTERNS):
        return "training"
    if any(re.search(pat, name) for pat in _INFERENCE_SCRIPT_PATTERNS):
        return "inference"
    if any(re.search(pat, name) for pat in _VALIDATION_PATTERNS):
        return "validation"
    return "other"


def _is_feature_file(path: str) -> bool:
    p = path.lower()
    keywords = (
        "feature", "featuregroup", "feature_group", "feature_store",
        "train", "training", "infer", "score", "register_model",
        "model_register", "feature_load", "load_feature",
    )
    return any(kw in p for kw in keywords)


def _parse_diff_sections(diff: str) -> list[tuple[str, list[tuple[str, int, str]]]]:
    """
    Returns list of (filepath, [(change_type, line_no, line_content)])
    change_type: "added" | "removed"
    """
    sections: list[tuple[str, list[tuple[str, int, str]]]] = []
    current_file = ""
    current_changes: list[tuple[str, int, str]] = []
    current_line = 0

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if current_file and current_changes:
                sections.append((current_file, current_changes))
            current_file = ""
            current_changes = []
            current_line = 0
        elif line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("@@ "):
            # @@ -a,b +c,d @@
            m = re.search(r"\+(\d+)", line)
            current_line = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            current_changes.append(("added", current_line, line[1:]))
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            current_changes.append(("removed", current_line, line[1:]))
        else:
            current_line += 1

    if current_file and current_changes:
        sections.append((current_file, current_changes))

    return sections


# Patterns for feature column definitions in various frameworks
_COLUMN_PATTERNS = [
    # Explicit column/feature assignments: feature_name = SomeType(...)
    (r'^(\w+)\s*=\s*(\w+Type|FloatType|IntType|StringType|BoolType|ArrayType|MapType)\s*\(', "type_defined"),
    # DataFrame column selection / assignment
    (r'df\[[\'"]([\w_]+)[\'"]\]', "df_column"),
    # Feature list literals
    (r'["\'](\w+_score|[\w_]*feature[\w_]*|[\w_]*metric[\w_]*)["\']', "feature_ref"),
    # SQL column in SELECT / CREATE TABLE
    (r'^\s*([\w_]+)\s+(FLOAT|INT|INTEGER|VARCHAR|STRING|DOUBLE|BOOLEAN|TIMESTAMP|DATE|NUMBER)', "sql_column"),
    # Pydantic / dataclass fields
    (r'^\s*([\w_]+)\s*:\s*(float|int|str|bool|Optional\[)', "typed_field"),
    # Column rename pattern
    (r'withColumnRenamed\s*\(\s*["\'](\w+)["\']\s*,\s*["\'](\w+)["\']', "rename"),
]

_TYPE_CHANGE_PATTERN = re.compile(
    r'(Optional\[[\w\[\]]+\]|float|int|str|bool|double|Float|Integer|String|Boolean)'
)


def _extract_column_changes(
    file_path: str, changes: list[tuple[str, int, str]]
) -> list[FeatureColumnChange]:
    results: list[FeatureColumnChange] = []
    seen: set[str] = set()

    added = {ln: txt for ct, ln, txt in changes if ct == "added"}
    removed = {ln: txt for ct, ln, txt in changes if ct == "removed"}

    # Detect renames: withColumnRenamed("old", "new")
    for ln, txt in added.items():
        m = re.search(r'withColumnRenamed\s*\(\s*["\'](\w+)["\']\s*,\s*["\'](\w+)["\']', txt)
        if m:
            old_name, new_name = m.group(1), m.group(2)
            key = f"rename:{old_name}→{new_name}"
            if key not in seen:
                seen.add(key)
                results.append(FeatureColumnChange(
                    column_name=old_name,
                    change_type="renamed",
                    new_type=new_name,
                    file=file_path, line=ln,
                    detail=f"Renamed '{old_name}' → '{new_name}'",
                ))

    # Detect type changes: same column name, different type annotation
    for ln, txt in added.items():
        for pat, kind in _COLUMN_PATTERNS:
            m = re.search(pat, txt.strip())
            if not m:
                continue
            col = m.group(1)
            if not col or col in seen:
                continue
            # Check if same column was removed (type change)
            for rln, rtxt in removed.items():
                rm = re.search(pat, rtxt.strip())
                if rm and rm.group(1) == col:
                    added_type = _TYPE_CHANGE_PATTERN.search(txt)
                    removed_type = _TYPE_CHANGE_PATTERN.search(rtxt)
                    if added_type and removed_type and added_type.group() != removed_type.group():
                        seen.add(col)
                        results.append(FeatureColumnChange(
                            column_name=col,
                            change_type="type_changed",
                            old_type=removed_type.group(),
                            new_type=added_type.group(),
                            file=file_path, line=ln,
                            detail=f"Type changed: {removed_type.group()} → {added_type.group()}",
                        ))
                    break
            else:
                # Pure addition
                if col not in seen and re.match(r'^[a-z_][a-z0-9_]{2,}$', col):
                    seen.add(col)
                    results.append(FeatureColumnChange(
                        column_name=col,
                        change_type="added",
                        file=file_path, line=ln,
                        detail=txt.strip()[:80],
                    ))

    # Detect removed columns
    for ln, txt in removed.items():
        for pat, kind in _COLUMN_PATTERNS:
            m = re.search(pat, txt.strip())
            if not m:
                continue
            col = m.group(1)
            if not col or col in seen:
                continue
            if col not in {c.column_name for c in results}:
                if re.match(r'^[a-z_][a-z0-9_]{2,}$', col):
                    seen.add(col)
                    results.append(FeatureColumnChange(
                        column_name=col,
                        change_type="removed",
                        file=file_path, line=ln,
                        detail=txt.strip()[:80],
                    ))

    return results


def _extract_job_name(content: str) -> str:
    """Extract job name from Databricks YAML content."""
    m = re.search(r'^name\s*:\s*(.+)$', content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _extract_feature_groups_from_content(content: str) -> list[str]:
    """Extract feature group / feature table names referenced in a file."""
    groups: list[str] = []
    # Pattern: strings that look like feature group names
    patterns = [
        r'feature_group[_\s]*=\s*["\']([^"\']+)["\']',
        r'feature_table[_\s]*=\s*["\']([^"\']+)["\']',
        r'FeatureGroup\s*\(\s*["\']([^"\']+)["\']',
        r'feature_store\.get_table\s*\(\s*["\']([^"\']+)["\']',
        r'notebook_path.*?/([\w_]+_feature[s]?)["\s]',
        r'"([\w_]*feature[s]?[\w_]*)"\s*:',
        r'feature_groups?\s*[:=]\s*\[([^\]]+)\]',
    ]
    for pat in patterns:
        for m in re.finditer(pat, content, re.IGNORECASE):
            name = m.group(1).strip().strip('"\'')
            if name and len(name) > 3:
                groups.append(name)
    return list(dict.fromkeys(groups))  # deduplicate preserving order


def _extract_job_changes(
    file_path: str, content: str, changes: list[tuple[str, int, str]]
) -> Optional[FeatureJobChange]:
    """Extract a job change from a Databricks YAML file."""
    if not file_path.endswith((".yml", ".yaml")):
        return None
    if not changes:
        return None

    job_name = _extract_job_name(content) or Path(file_path).stem
    job_kind = _classify_file(file_path)
    if job_kind == "other":
        return None

    feature_groups = _extract_feature_groups_from_content(content)
    changed_lines = [txt for _, _, txt in changes if txt.strip()]
    detail_sample = "; ".join(changed_lines[:3])[:120]

    return FeatureJobChange(
        job_name=job_name,
        job_kind=job_kind,
        change_type="modified",
        feature_groups=feature_groups,
        file=file_path,
        detail=detail_sample,
    )


def _find_feature_consumers(
    column_names: list[str],
    feature_groups: list[str],
    file_contents: dict[str, str],
) -> dict[str, list[FeatureConsumer]]:
    """Find all references to changed columns/groups across fetched files."""
    consumers: dict[str, list[FeatureConsumer]] = {}
    search_terms = list(dict.fromkeys(column_names + feature_groups))

    for term in search_terms:
        if not term or len(term) < 3:
            continue
        pattern = re.compile(r'\b' + re.escape(term) + r'\b', re.IGNORECASE)
        hits: list[FeatureConsumer] = []

        for path, content in file_contents.items():
            for i, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    kind = _classify_file(path)
                    consumer_kind = kind if kind != "other" else ""
                    hits.append(FeatureConsumer(
                        file=path,
                        line=i,
                        snippet=line.strip()[:100],
                        consumer_kind=consumer_kind,
                    ))

        if hits:
            consumers[term] = hits[:20]  # cap per term

    return consumers


def compute_feature_store_extract(
    diff: str,
    file_contents: dict[str, str],
) -> FeatureStoreExtract:
    """
    Deterministically extract feature store artifacts from a diff.

    Returns FeatureStoreExtract with:
    - column_changes: feature columns added/removed/renamed/type-changed
    - job_changes: load/register/train jobs modified
    - consumers: where changed features/columns are referenced in other files
    - feature_groups_affected: deduplicated list of affected feature groups
    """
    result = FeatureStoreExtract()
    diff_sections = _parse_diff_sections(diff)

    for file_path, changes in diff_sections:
        if not _is_feature_file(file_path):
            continue

        # Column changes from Python / SQL files
        if file_path.endswith((".py", ".sql", ".ipynb")):
            cols = _extract_column_changes(file_path, changes)
            result.column_changes.extend(cols)

        # Job changes from YAML files
        if file_path.endswith((".yml", ".yaml")):
            content = file_contents.get(file_path, "")
            if not content:
                # Reconstruct from diff added lines
                content = "\n".join(txt for _, _, txt in changes if True)
            job = _extract_job_changes(file_path, content, changes)
            if job:
                result.job_changes.append(job)
                result.feature_groups_affected.extend(job.feature_groups)

    # Deduplicate feature groups
    result.feature_groups_affected = list(dict.fromkeys(result.feature_groups_affected))

    # Find consumers of changed columns and feature groups
    changed_cols = [c.column_name for c in result.column_changes]
    result.consumers = _find_feature_consumers(
        changed_cols, result.feature_groups_affected, file_contents
    )
    result.files_analyzed = len(file_contents)

    return result


def format_as_markdown(extract: FeatureStoreExtract) -> str:
    if not extract.column_changes and not extract.job_changes:
        return ""

    lines = ["## Feature Store Extract (pre-computed)\n"]

    # Affected feature groups summary
    if extract.feature_groups_affected:
        lines.append(f"**Affected feature groups:** {', '.join(extract.feature_groups_affected)}\n")

    # Column changes
    if extract.column_changes:
        lines.append("### Feature Column Changes\n")
        lines.append("| Column | Change | Type | File | Line |")
        lines.append("|---|---|---|---|---|")
        for c in extract.column_changes:
            type_info = f"{c.old_type} → {c.new_type}" if c.old_type else c.new_type or "—"
            lines.append(f"| `{c.column_name}` | {c.change_type} | {type_info} | {c.file} | {c.line} |")
        lines.append("")

    # Job changes
    if extract.job_changes:
        lines.append("### Feature Job Changes\n")
        lines.append("| Job | Kind | Feature Groups | File |")
        lines.append("|---|---|---|---|")
        for j in extract.job_changes:
            groups = ", ".join(j.feature_groups) if j.feature_groups else "—"
            lines.append(f"| `{j.job_name}` | {j.job_kind} | {groups} | {j.file} |")
        lines.append("")

    # Consumers
    if extract.consumers:
        lines.append("### Consumers of Changed Features\n")
        total = sum(len(v) for v in extract.consumers.values())
        lines.append(f"Found **{total}** reference(s) across {extract.files_analyzed} file(s):\n")
        for term, hits in list(extract.consumers.items())[:8]:
            lines.append(f"**`{term}`** ({len(hits)} reference(s))")
            for h in hits[:4]:
                kind = f"[{h.consumer_kind}] " if h.consumer_kind else ""
                lines.append(f"  - {kind}`{h.file}:{h.line}` — {h.snippet}")
            lines.append("")

    return "\n".join(lines)
