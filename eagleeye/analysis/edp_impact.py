"""EDP (Enterprise Data Platform) impact analysis.

Deterministically extracts pipeline artifacts from a diff and maps
job dependency chains before Claude sees any data. Gives the Lineage Agent
a pre-computed dependency graph instead of raw YAML to parse.

Detects:
  - Databricks job config changes (tasks, clusters, schedules, dependencies)
  - fail_on_run_failure flags — identifies silent failure risks
  - Job dependency chains — maps which jobs feed which downstream jobs
  - Schedule changes — identifies timing conflicts with dependent jobs
  - dbt model ref() dependency changes
  - Snowflake / Spark pipeline config changes

Cross-file mapping:
  - Scans all fetched YAML configs to build the full job dependency graph
  - Identifies downstream consumers of every changed job
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional



@dataclass
class TaskConfig:
    task_key: str
    notebook_path: str = ""
    depends_on: list[str] = field(default_factory=list)
    fail_on_run_failure: Optional[bool] = None
    cluster_size: str = ""


@dataclass
class JobConfig:
    job_name: str
    file: str
    tasks: list[TaskConfig] = field(default_factory=list)
    schedule: str = ""                   # cron expression if set
    max_concurrent_runs: int = 1
    tags: list[str] = field(default_factory=list)


@dataclass
class ChangedJob:
    job_name: str
    file: str
    change_type: str                     # "added" | "modified" | "removed"
    # What specifically changed
    tasks_added: list[str] = field(default_factory=list)
    tasks_removed: list[str] = field(default_factory=list)
    tasks_modified: list[str] = field(default_factory=list)
    fail_on_run_failure_changed: bool = False
    fail_on_run_failure_value: Optional[bool] = None
    schedule_changed: bool = False
    old_schedule: str = ""
    new_schedule: str = ""
    cluster_changed: bool = False
    detail: str = ""


@dataclass
class DependencyRisk:
    """A downstream job that may be affected by a changed upstream job."""
    upstream_job: str
    downstream_job: str
    downstream_file: str
    risk: str                            # "silent_cascade" | "schedule_conflict" | "missing_output"
    detail: str


@dataclass
class DbtModelChange:
    model_name: str
    file: str
    change_type: str                     # "added" | "modified" | "removed"
    refs_changed: list[str] = field(default_factory=list)   # ref() dependencies changed
    detail: str = ""


@dataclass
class EDPExtract:
    changed_jobs: list[ChangedJob] = field(default_factory=list)
    dependency_risks: list[DependencyRisk] = field(default_factory=list)
    dbt_changes: list[DbtModelChange] = field(default_factory=list)
    silent_failure_jobs: list[str] = field(default_factory=list)  # jobs with fail_on_run_failure:false
    files_analyzed: int = 0


def _is_pipeline_file(path: str) -> bool:
    p = path.lower()
    if p.endswith((".yml", ".yaml")):
        return True
    if p.endswith((".sql",)) and any(kw in p for kw in ("dbt", "model", "pipeline")):
        return True
    return False


def _extract_job_name(content: str) -> str:
    m = re.search(r'^name\s*:\s*(.+)$', content, re.MULTILINE)
    return m.group(1).strip().strip('"\'') if m else ""


def _extract_schedule(content: str) -> str:
    """Extract cron schedule from Databricks job YAML."""
    # quartz_cron_expression or cron_expression
    m = re.search(r'(?:quartz_cron_expression|cron_expression)\s*:\s*["\']?([^"\'\n]+)["\']?', content)
    if m:
        return m.group(1).strip()
    m = re.search(r'schedule\s*:\s*\n\s+(?:cron\s*:\s*)?["\']?([^\n"\']+)["\']?', content)
    return m.group(1).strip() if m else ""


def _extract_tasks(content: str) -> list[TaskConfig]:
    """Extract task definitions from a Databricks job YAML."""
    tasks: list[TaskConfig] = []

    # Find all task blocks
    task_blocks = re.split(r'\n\s*-\s+task_key\s*:', content)
    for block in task_blocks[1:]:  # skip first element (before first task)
        lines = block.splitlines()
        task_key = lines[0].strip().strip('"\'') if lines else ""
        if not task_key:
            continue

        task = TaskConfig(task_key=task_key)

        # notebook path
        nb = re.search(r'notebook_path\s*:\s*["\']?([^"\'\n]+)["\']?', block)
        if nb:
            task.notebook_path = nb.group(1).strip()

        # depends_on
        dep_block = re.search(r'depends_on\s*:\s*\n((?:\s+-.*\n)*)', block)
        if dep_block:
            task.depends_on = re.findall(r'task_key\s*:\s*["\']?(\w[\w_-]*)["\']?', dep_block.group(1))

        # fail_on_run_failure
        forf = re.search(r'fail_on_run_failure\s*:\s*(true|false)', block, re.IGNORECASE)
        if forf:
            task.fail_on_run_failure = forf.group(1).lower() == "true"

        # cluster / node type
        nc = re.search(r'node_type_id\s*:\s*["\']?([^"\'\n]+)["\']?', block)
        wk = re.search(r'num_workers\s*:\s*(\d+)', block)
        if nc or wk:
            task.cluster_size = f"{nc.group(1) if nc else ''} x{wk.group(1) if wk else '?'}"

        tasks.append(task)

    return tasks


def _parse_job_config(file_path: str, content: str) -> Optional[JobConfig]:
    """Parse a Databricks job YAML into a JobConfig."""
    if not content.strip():
        return None
    job_name = _extract_job_name(content)
    if not job_name:
        return None
    tasks = _extract_tasks(content)
    schedule = _extract_schedule(content)
    return JobConfig(
        job_name=job_name,
        file=file_path,
        tasks=tasks,
        schedule=schedule,
    )


def _parse_diff_sections(diff: str) -> list[tuple[str, str, str]]:
    """
    Returns (file_path, added_text, removed_text) per file in the diff.
    """
    sections: list[tuple[str, str, str]] = []
    current_file = ""
    added_lines: list[str] = []
    removed_lines: list[str] = []

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if current_file:
                sections.append((current_file, "\n".join(added_lines), "\n".join(removed_lines)))
            current_file = ""
            added_lines, removed_lines = [], []
        elif line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed_lines.append(line[1:])

    if current_file:
        sections.append((current_file, "\n".join(added_lines), "\n".join(removed_lines)))

    return sections


def _detect_job_changes(
    file_path: str, added_text: str, removed_text: str, full_content: str
) -> Optional[ChangedJob]:
    """Detect what specifically changed in a job YAML file."""
    if not full_content.strip() and not added_text.strip():
        return None

    job_name = _extract_job_name(full_content or added_text)
    if not job_name:
        job_name = Path(file_path).stem

    # Determine if added/removed/modified
    if not removed_text.strip() and added_text.strip():
        change_type = "added"
    elif removed_text.strip() and not added_text.strip():
        change_type = "removed"
    else:
        change_type = "modified"

    changed = ChangedJob(job_name=job_name, file=file_path, change_type=change_type)

    # Detect fail_on_run_failure changes
    added_forf = re.search(r'fail_on_run_failure\s*:\s*(true|false)', added_text, re.IGNORECASE)
    removed_forf = re.search(r'fail_on_run_failure\s*:\s*(true|false)', removed_text, re.IGNORECASE)
    if added_forf:
        changed.fail_on_run_failure_changed = True
        changed.fail_on_run_failure_value = added_forf.group(1).lower() == "true"
    elif removed_forf and not added_forf:
        changed.fail_on_run_failure_changed = True
        changed.fail_on_run_failure_value = None  # removed entirely

    # Detect schedule changes
    old_sched = _extract_schedule(removed_text)
    new_sched = _extract_schedule(added_text)
    if old_sched != new_sched and (old_sched or new_sched):
        changed.schedule_changed = True
        changed.old_schedule = old_sched
        changed.new_schedule = new_sched

    # Detect added/removed tasks
    added_tasks = re.findall(r'task_key\s*:\s*["\']?(\w[\w_-]*)["\']?', added_text)
    removed_tasks = re.findall(r'task_key\s*:\s*["\']?(\w[\w_-]*)["\']?', removed_text)
    added_set, removed_set = set(added_tasks), set(removed_tasks)
    changed.tasks_added = list(added_set - removed_set)
    changed.tasks_removed = list(removed_set - added_set)
    changed.tasks_modified = list(added_set & removed_set)

    # Detect cluster size changes
    old_workers = re.findall(r'num_workers\s*:\s*(\d+)', removed_text)
    new_workers = re.findall(r'num_workers\s*:\s*(\d+)', added_text)
    if old_workers != new_workers:
        changed.cluster_changed = True

    # Build a brief detail string
    parts = []
    if changed.fail_on_run_failure_changed:
        val = str(changed.fail_on_run_failure_value).lower() if changed.fail_on_run_failure_value is not None else "removed"
        parts.append(f"fail_on_run_failure: {val}")
    if changed.schedule_changed:
        parts.append(f"schedule: {changed.old_schedule or 'none'} → {changed.new_schedule or 'none'}")
    if changed.tasks_added:
        parts.append(f"tasks added: {', '.join(changed.tasks_added)}")
    if changed.tasks_removed:
        parts.append(f"tasks removed: {', '.join(changed.tasks_removed)}")
    if changed.cluster_changed:
        parts.append(f"workers: {old_workers} → {new_workers}")
    changed.detail = "; ".join(parts)

    return changed


def _detect_dbt_changes(
    file_path: str, added_text: str, removed_text: str
) -> Optional[DbtModelChange]:
    """Detect dbt model changes from .sql or .yml dbt files."""
    if not (file_path.lower().endswith(".sql") or "dbt" in file_path.lower()):
        return None

    model_name = Path(file_path).stem
    added_refs = re.findall(r"\{\{\s*ref\s*\(\s*['\"](\w+)['\"]\s*\)\s*\}\}", added_text)
    removed_refs = re.findall(r"\{\{\s*ref\s*\(\s*['\"](\w+)['\"]\s*\)\s*\}\}", removed_text)

    if not added_refs and not removed_refs and not added_text.strip():
        return None

    change_type = "added" if not removed_text.strip() else "modified"
    refs_changed = list(set(added_refs) ^ set(removed_refs))

    return DbtModelChange(
        model_name=model_name,
        file=file_path,
        change_type=change_type,
        refs_changed=refs_changed,
        detail=f"refs changed: {refs_changed}" if refs_changed else "",
    )


def _build_dependency_graph(file_contents: dict[str, str]) -> dict[str, list[str]]:
    """
    Scans all fetched YAML files and builds a map:
      job_name → [downstream_job_names that depend on it]

    Returns reverse dependency map (upstream → list of downstreams).
    """
    # First pass: parse all job configs
    all_jobs: dict[str, JobConfig] = {}
    for path, content in file_contents.items():
        if not _is_pipeline_file(path):
            continue
        cfg = _parse_job_config(path, content)
        if cfg:
            all_jobs[cfg.job_name] = cfg

    # Build reverse map: for each job, find tasks that depend_on other tasks
    # In Databricks, depends_on is within a job (task → task), not job → job
    # But we also check for run_job tasks that reference other jobs by name
    reverse_map: dict[str, list[str]] = {}

    for job_name, cfg in all_jobs.items():
        for task in cfg.tasks:
            for dep in task.depends_on:
                # dep is a task_key — find which job it belongs to
                if dep not in reverse_map:
                    reverse_map[dep] = []
                reverse_map[dep].append(f"{job_name}.{task.task_key}")

    # Also scan for run_job_task references (one job triggering another)
    for path, content in file_contents.items():
        job_refs = re.findall(r'job_name\s*:\s*["\']?([^"\'\n]+)["\']?', content)
        trigger_job = _extract_job_name(content)
        if trigger_job:
            for ref in job_refs:
                ref = ref.strip()
                if ref != trigger_job:
                    if ref not in reverse_map:
                        reverse_map[ref] = []
                    reverse_map[ref].append(trigger_job)

    return reverse_map


def _assess_dependency_risks(
    changed_jobs: list[ChangedJob],
    dependency_graph: dict[str, list[str]],
    file_contents: dict[str, str],
) -> list[DependencyRisk]:
    """
    For each changed job, find downstream consumers and assess risk.
    """
    risks: list[DependencyRisk] = []
    seen: set[tuple[str, str]] = set()

    for job in changed_jobs:
        downstreams = dependency_graph.get(job.job_name, [])

        for downstream in downstreams:
            key = (job.job_name, downstream)
            if key in seen:
                continue
            seen.add(key)

            # Determine risk type
            if job.fail_on_run_failure_value is False:
                risk_type = "silent_cascade"
                detail = (
                    f"'{job.job_name}' has fail_on_run_failure: false. "
                    f"If it fails, '{downstream}' will run against missing/stale output."
                )
            elif job.schedule_changed:
                risk_type = "schedule_conflict"
                detail = (
                    f"'{job.job_name}' schedule changed ({job.old_schedule} → {job.new_schedule}). "
                    f"'{downstream}' may start before '{job.job_name}' completes."
                )
            elif job.tasks_removed:
                risk_type = "missing_output"
                detail = (
                    f"Tasks removed from '{job.job_name}': {job.tasks_removed}. "
                    f"'{downstream}' may depend on their output."
                )
            else:
                risk_type = "missing_output"
                detail = f"'{job.job_name}' changed. '{downstream}' depends on its output."

            # Find the file for the downstream job
            downstream_file = ""
            for path, content in file_contents.items():
                name = _extract_job_name(content)
                if name and (downstream.startswith(name) or name in downstream):
                    downstream_file = path
                    break

            risks.append(DependencyRisk(
                upstream_job=job.job_name,
                downstream_job=downstream,
                downstream_file=downstream_file,
                risk=risk_type,
                detail=detail,
            ))

    return risks


def compute_edp_extract(
    diff: str,
    file_contents: dict[str, str],
) -> EDPExtract:
    """
    Deterministically extract EDP pipeline artifacts from a diff.

    Returns EDPExtract with:
    - changed_jobs: Databricks/pipeline jobs that changed and what specifically changed
    - dependency_risks: downstream jobs at risk from each changed job
    - dbt_changes: dbt model changes with ref() dependency shifts
    - silent_failure_jobs: jobs with fail_on_run_failure: false introduced
    """
    result = EDPExtract()
    diff_sections = _parse_diff_sections(diff)

    # Extract changes from diff
    for file_path, added_text, removed_text in diff_sections:
        if not _is_pipeline_file(file_path):
            continue

        full_content = file_contents.get(file_path, added_text)

        # Databricks / generic YAML job
        if file_path.endswith((".yml", ".yaml")):
            job_change = _detect_job_changes(file_path, added_text, removed_text, full_content)
            if job_change:
                result.changed_jobs.append(job_change)
                if job_change.fail_on_run_failure_value is False:
                    result.silent_failure_jobs.append(job_change.job_name)

        # dbt model
        if file_path.endswith(".sql") or "models/" in file_path.lower():
            dbt = _detect_dbt_changes(file_path, added_text, removed_text)
            if dbt:
                result.dbt_changes.append(dbt)

    # Build dependency graph from all fetched files and assess risks
    if result.changed_jobs and file_contents:
        dep_graph = _build_dependency_graph(file_contents)
        result.dependency_risks = _assess_dependency_risks(
            result.changed_jobs, dep_graph, file_contents
        )

    result.files_analyzed = len(file_contents)
    return result


def format_as_markdown(extract: EDPExtract) -> str:
    if not extract.changed_jobs and not extract.dbt_changes:
        return ""

    lines = ["## EDP Impact Extract (pre-computed)\n"]

    # Silent failure warnings — most critical, surface first
    if extract.silent_failure_jobs:
        lines.append(f"⚠️ **Jobs with fail_on_run_failure: false:** {', '.join(extract.silent_failure_jobs)}\n")

    # Changed jobs table
    if extract.changed_jobs:
        lines.append("### Changed Pipeline Jobs\n")
        lines.append("| Job | Change | fail_on_run_failure | Schedule | Tasks Added | Tasks Removed |")
        lines.append("|---|---|---|---|---|---|")
        for j in extract.changed_jobs:
            forf = str(j.fail_on_run_failure_value).lower() if j.fail_on_run_failure_value is not None else "—"
            sched = "changed" if j.schedule_changed else "—"
            added = ", ".join(j.tasks_added) if j.tasks_added else "—"
            removed = ", ".join(j.tasks_removed) if j.tasks_removed else "—"
            lines.append(f"| `{j.job_name}` | {j.change_type} | {forf} | {sched} | {added} | {removed} |")
        lines.append("")

    # Dependency risks
    if extract.dependency_risks:
        lines.append("### Dependency Chain Risks\n")
        for r in extract.dependency_risks:
            risk_badge = {
                "silent_cascade": "🔴 SILENT CASCADE",
                "schedule_conflict": "🟡 SCHEDULE CONFLICT",
                "missing_output": "🟠 MISSING OUTPUT",
            }.get(r.risk, r.risk.upper())
            lines.append(f"**{risk_badge}**")
            lines.append(f"  {r.detail}")
            lines.append("")

    # dbt changes
    if extract.dbt_changes:
        lines.append("### dbt Model Changes\n")
        lines.append("| Model | Change | refs Changed |")
        lines.append("|---|---|---|")
        for d in extract.dbt_changes:
            refs = ", ".join(d.refs_changed) if d.refs_changed else "—"
            lines.append(f"| `{d.model_name}` | {d.change_type} | {refs} |")
        lines.append("")

    return "\n".join(lines)
