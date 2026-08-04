"""Rich terminal rendering for EagleEye.

Feature modules return Pydantic models — this module renders them.
Nothing in the features/ layer should print directly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..integrations.anthropic.client import TokenUsage
from ..analysis.schema_impact import SchemaImpactResult
from ..core.models import BugScanResult, DiagramResult, PRReviewResult, RepoEvaluationResult, RepoMap, RepoSummaryResult
from ..features.repo_auditor import AuditResult

console = Console()

# Severity colour map
_SEVERITY_STYLE = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
    "info": "dim",
}

_VERDICT_LABEL = {
    "approve": "Okay to merge",
    "request_changes": "Let's revisit",
    "comment": "Needs attention",
}

_VERDICT_STYLE = {
    "approve": "bold green",
    "request_changes": "bold red",
    "comment": "bold yellow",
}

_RISK_STYLE = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "green",
}



def display_pr_review(
    result: PRReviewResult,
    pr_url: str = "",
    pr_info: Optional[dict] = None,
) -> None:
    """Render a PR review result.

    pr_info: optional dict with keys number (int), title (str), owner_repo (str)
    """
    _sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

    header = Text()
    if pr_info:
        pr_ref = f"PR #{pr_info.get('number', '')} · {pr_info.get('title', '')}"
        header.append(f"{pr_ref}\n", style="bold")
    if result.requested_by:
        header.append(f"Requested by: @{result.requested_by}\n", style="")
    if pr_info and pr_info.get("owner_repo"):
        header.append(f"{pr_info['owner_repo']}  ·  {date.today().isoformat()}", style="dim")
    elif pr_url:
        header.append(f"{date.today().isoformat()}", style="dim")
    if pr_url:
        header.append(f"\n{pr_url}", style="dim blue")
    console.print(Panel(header, title="[bold]EagleEye Code Review[/bold]", border_style="blue"))

    verdict_label = _VERDICT_LABEL.get(result.overall_verdict, result.overall_verdict)
    verdict_style = _VERDICT_STYLE.get(result.overall_verdict, "bold white")
    risk_style = _RISK_STYLE.get(result.risk_level, "white")
    verdict_text = Text()
    verdict_text.append("Review: ", style="bold")
    verdict_text.append(verdict_label, style=verdict_style)
    verdict_text.append("   ·   Risk: ", style="bold")
    verdict_text.append(result.risk_level.upper(), style=risk_style)
    console.print(verdict_text)
    console.print(Rule(style="dim"))

    # 3. Summary
    console.print(f"\n{result.summary}\n")

    # 4. Findings (Critical / High / Medium)
    high_priority = [
        fc for fc in result.file_comments if fc.severity in ("critical", "high", "medium")
    ]
    if high_priority:
        sorted_hp = sorted(high_priority, key=lambda c: _sev_order.get(c.severity, 99))

        # Count by severity for title
        crit_count = sum(1 for fc in sorted_hp if fc.severity == "critical")
        high_count = sum(1 for fc in sorted_hp if fc.severity == "high")
        med_count = sum(1 for fc in sorted_hp if fc.severity == "medium")

        findings_text = Text()
        current_sev = None
        for fc in sorted_hp:
            if fc.severity != current_sev:
                current_sev = fc.severity
                sev_style = _SEVERITY_STYLE.get(fc.severity, "white")
                findings_text.append(f"\n{fc.severity.upper()}\n", style=f"{sev_style} bold")
            loc = fc.file
            if fc.line_range:
                loc += f":{fc.line_range}"
            findings_text.append("  · ", style="dim")
            findings_text.append(fc.comment, style="white")
            findings_text.append(f"  —  {loc}\n", style="dim cyan")
        has_critical = any(fc.severity == "critical" for fc in high_priority)
        border = "red" if has_critical else "yellow"
        title_counts = f" ({crit_count} 🚨 critical, {high_count} 🔴 high, {med_count} 🟡 medium)" if any([crit_count, high_count, med_count]) else ""
        console.print(Panel(findings_text, title=f"[bold]Findings{title_counts}[/bold]", border_style=border))

    if result.blocking_issues:
        blocking_count = len(result.blocking_issues)
        blocking_text = "\n".join(f"  [red]•[/red] {issue}" for issue in result.blocking_issues)
        console.print(Panel(
            blocking_text, title=f"[bold red]Blocking Issues ({blocking_count})[/bold red]", border_style="red"
        ))

    if result.feature_store_impact and result.feature_store_impact.affected_features:
        fsi = result.feature_store_impact
        if fsi.summary:
            console.print(
                f"\n[bold yellow]Feature Store Impact Analysis[/bold yellow]\n{fsi.summary}"
            )
        else:
            console.print("\n[bold yellow]Feature Store Impact Analysis[/bold yellow]")
        fsi_table = Table(box=box.ROUNDED, show_lines=True, expand=True)
        fsi_table.add_column("Feature", style="cyan")
        fsi_table.add_column("Change", width=16)
        fsi_table.add_column("Downstream Models")
        fsi_table.add_column("Details")
        for af in fsi.affected_features:
            style = _CHANGE_TYPE_STYLE.get(af.change_type, "white")
            models = ", ".join(af.downstream_models) if af.downstream_models else "—"
            fsi_table.add_row(
                af.name, Text(af.change_type.upper(), style=style), models, af.details
            )
        console.print(fsi_table)

    if result.edp_impact and result.edp_impact.affected_pipelines:
        from ..workflows.review.formatting import edp_downstream
        edp = result.edp_impact
        rows = [
            (ap.name, ap.change_type, edp_downstream(ap.details))
            for ap in edp.affected_pipelines
            if edp_downstream(ap.details)
        ]
        if rows:
            if edp.summary:
                console.print(f"\n[bold yellow]EDP Impact Analysis[/bold yellow]\n{edp.summary}")
            else:
                console.print("\n[bold yellow]EDP Impact Analysis[/bold yellow]")
            edp_table = Table(box=box.ROUNDED, show_lines=True, expand=True)
            edp_table.add_column("Object", style="cyan")
            edp_table.add_column("Downstream", style="white")
            for name, change_type, downstream in rows:
                style = _CHANGE_TYPE_STYLE.get(change_type, "white")
                edp_table.add_row(
                    f"{name} ({Text(change_type.upper(), style=style)})", downstream
                )
            console.print(edp_table)

    misc = [fc for fc in result.file_comments if fc.severity in ("low", "info")]
    if misc:
        misc_count = len(misc)
        misc_lines = []
        for fc in misc:
            sev_style = _SEVERITY_STYLE.get(fc.severity, "dim")
            loc = f"{fc.file}:{fc.line_range}" if fc.line_range else fc.file
            sev_tag = fc.severity.upper()
            entry = f"  [{sev_style}]{sev_tag}[/{sev_style}] [dim]{loc}[/dim] — {fc.comment}"
            misc_lines.append(entry)
            if fc.suggestion:
                misc_lines.append(f"    [dim]→ {fc.suggestion}[/dim]")
        console.print(Panel(
            "\n".join(misc_lines), title=f"[bold]Misc Issues ({misc_count})[/bold]", border_style="dim"
        ))

    if result.positive_highlights:
        highlight_count = len(result.positive_highlights)
        pos_text = "\n".join(f"  [green]✓[/green] {h}" for h in result.positive_highlights)
        console.print(Panel(
            pos_text, title=f"[bold green]Positive Highlights ({highlight_count})[/bold green]", border_style="green"
        ))

    if high_priority:
        lines = []
        for fc in sorted(high_priority, key=lambda c: _sev_order.get(c.severity, 99)):
            sev_style = _SEVERITY_STYLE.get(fc.severity, "white")
            loc = f"{fc.file}:{fc.line_range}" if fc.line_range else fc.file
            lines.append(f"[{sev_style}]{fc.severity.upper()}[/{sev_style}] [cyan]{loc}[/cyan]")
            lines.append(fc.comment)
            if fc.suggestion:
                lines.append(f"[dim]→ {fc.suggestion}[/dim]")
            lines.append("")
        console.print(Panel(
            "\n".join(lines).rstrip(),
            title="[bold]Remediation Suggestions[/bold]",
            border_style="yellow",
        ))

    console.print("")



def display_agent_breakdown(agent_results: list) -> None:
    """Show per-agent findings before synthesis — for debugging/transparency."""
    if not agent_results:
        return

    _agent_emoji = {
        "pr": "🔍",
        "schema": "🗄️",
        "lineage": "🔗",
        "feature": "🧬",
        "arch_drift": "🏗️",
    }

    console.print(Rule("[bold]Agent Breakdown[/bold]", style="dim"))

    for ar in agent_results:
        emoji = _agent_emoji.get(ar.agent, "·")
        if ar.error:
            console.print(f"  {emoji} [bold]{ar.agent}[/bold]  [red]FAILED — {ar.error}[/red]")
            continue

        count = len(ar.findings)
        badge = f"[dim]{count} finding{'s' if count != 1 else ''}[/dim]"
        console.print(f"\n  {emoji} [bold]{ar.agent}[/bold]  {badge}")

        if ar.summary:
            console.print(f"  [dim]{ar.summary}[/dim]")

        if ar.findings:
            t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            t.add_column("Sev", width=9)
            t.add_column("File", style="cyan", max_width=38)
            t.add_column("Title")
            for f in ar.findings:
                sev_style = _SEVERITY_STYLE.get(f.severity, "white")
                loc = f.file
                if f.line_range:
                    loc += f":{f.line_range}"
                t.add_row(Text(f.severity.upper(), style=sev_style), loc, f.title)
            console.print(t)

    console.print(Rule(style="dim"))
    console.print("")



def display_repo_summary(result: RepoSummaryResult, repo_url: str = "") -> None:
    header = Text()
    header.append(result.project_name, style="bold")
    if repo_url:
        header.append(f"\n{repo_url}", style="dim")
    header.append(f"\n\n{result.purpose}")
    console.print(Panel(header, title="[bold]Repository Analysis[/bold]", border_style="blue"))

    # Tech stack
    if result.tech_stack:
        stack_text = "  " + "  |  ".join(f"[cyan]{t}[/cyan]" for t in result.tech_stack)
        console.print(Panel(stack_text, title="Tech Stack", border_style="cyan", padding=(0, 1)))

    # Architecture layers
    if result.architecture_layers:
        table = Table(title="Architecture", box=box.SIMPLE_HEAVY, show_lines=True)
        table.add_column("Layer", style="bold cyan", width=20)
        table.add_column("Description")
        table.add_column("Key Files", style="dim", max_width=45)
        for layer in result.architecture_layers:
            table.add_row(layer.name, layer.description, ", ".join(layer.key_files))
        console.print(table)

    # Entry points
    if result.entry_points:
        ep_text = "\n".join(f"  [yellow]▶[/yellow] {ep}" for ep in result.entry_points)
        console.print(Panel(ep_text, title="Entry Points", border_style="yellow"))

    # Onboarding steps
    if result.onboarding_steps:
        steps = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(result.onboarding_steps))
        console.print(Panel(steps, title="[bold]Onboarding Steps[/bold]", border_style="green"))

    # External dependencies
    if result.external_dependencies:
        deps = "  " + "  •  ".join(result.external_dependencies)
        console.print(Panel(deps, title="External Dependencies", border_style="dim", padding=(0, 1)))

    # Open questions
    if result.open_questions:
        q_text = "\n".join(f"  [yellow]?[/yellow] {q}" for q in result.open_questions)
        console.print(Panel(q_text, title="Open Questions", border_style="yellow"))



def display_bug_scan(result: BugScanResult) -> None:
    # Header with counts
    badge_parts = []
    if result.critical_count:
        badge_parts.append(f"[bold red]{result.critical_count} CRITICAL[/bold red]")
    if result.high_count:
        badge_parts.append(f"[red]{result.high_count} HIGH[/red]")
    other = len(result.findings) - result.critical_count - result.high_count
    if other:
        badge_parts.append(f"[yellow]{other} OTHER[/yellow]")

    badge = "  |  ".join(badge_parts) or "[green]No issues found[/green]"
    console.print(Panel(badge, title=f"[bold]Bug Scan: {result.scan_target}[/bold]", border_style="red" if result.critical_count else "yellow"))

    # Executive summary
    console.print(Panel(result.executive_summary, title="Executive Summary", border_style="blue"))

    # Most urgent fix
    if result.most_urgent_fix:
        console.print(Panel(
            f"[bold red]{result.most_urgent_fix}[/bold red]",
            title="[red]Most Urgent Fix[/red]",
            border_style="red",
        ))

    # Findings table
    if result.findings:
        table = Table(title="Findings", box=box.ROUNDED, show_lines=True, expand=True)
        table.add_column("Sev", width=9)
        table.add_column("File", style="cyan", max_width=35)
        table.add_column("Category", width=14)
        table.add_column("Title")
        table.add_column("Fix", max_width=40)

        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_findings = sorted(result.findings, key=lambda f: order.get(f.severity, 99))

        for f in sorted_findings:
            sev_style = _SEVERITY_STYLE.get(f.severity, "white")
            loc = f.file
            if f.line_range:
                loc += f":{f.line_range}"
            cwe = f" [dim]({f.cwe_id})[/dim]" if f.cwe_id else ""
            table.add_row(
                Text(f.severity.upper(), style=sev_style),
                loc,
                f.category + cwe,
                f.title,
                f.fix_suggestion,
            )
        console.print(table)
    else:
        console.print("[green]No findings.[/green]\n")


def display_audit(
    result: AuditResult,
    branch: str = "",
    files_scanned: Optional[list[str]] = None,
) -> None:
    """Render deterministic repo health check results."""
    badge_parts = []
    if result.critical_count:
        badge_parts.append(f"[bold red]{result.critical_count} CRITICAL[/bold red]")
    if result.high_count:
        badge_parts.append(f"[red]{result.high_count} HIGH[/red]")
    medium = sum(1 for f in result.findings if f.severity == "medium")
    low = sum(1 for f in result.findings if f.severity == "low")
    if medium:
        badge_parts.append(f"[yellow]{medium} MEDIUM[/yellow]")
    if low:
        badge_parts.append(f"[cyan]{low} LOW[/cyan]")

    badge = "  |  ".join(badge_parts) or "[green]No issues found[/green]"
    title = f"[bold]Repo Audit: {result.repo}[/bold]"
    if branch:
        title += f" [dim]({branch})[/dim]"
    border = "red" if result.critical_count else ("yellow" if result.findings else "green")
    console.print(Panel(badge, title=title, border_style=border))
    console.print(f"[dim]{result.summary()}[/dim]\n")

    if result.findings:
        table = Table(title="Findings", box=box.ROUNDED, show_lines=True, expand=True)
        table.add_column("Sev", width=9)
        table.add_column("File", style="cyan", max_width=35)
        table.add_column("Category", width=14)
        table.add_column("Checker", width=22)
        table.add_column("Issue")
        table.add_column("Fix", max_width=40)

        for f in result.findings:
            sev_style = _SEVERITY_STYLE.get(f.severity, "white")
            loc = f.file + (f" (line {f.line})" if f.line else "")
            table.add_row(
                Text(f.severity.upper(), style=sev_style),
                loc,
                f.category,
                f.checker,
                f.title,
                f.fix,
            )
        console.print(table)
    else:
        console.print("[green]No issues found.[/green]\n")

    if files_scanned:
        preview = ", ".join(files_scanned[:8])
        if len(files_scanned) > 8:
            preview += f" … (+{len(files_scanned) - 8} more)"
        console.print(f"[dim]Files scanned ({len(files_scanned)}): {preview}[/dim]\n")


def display_repo_map(result: RepoMap, saved_path: Optional[Path] = None) -> None:
    """Render a built RepoMap summary."""
    header = (
        f"[bold]{result.owner}/{result.repo}[/bold]  "
        f"[dim]branch {result.branch} · {result.file_count} files[/dim]"
    )
    console.print(Panel(header, title="[bold]Repo Map[/bold]", border_style="blue"))

    if result.description:
        console.print(Panel(result.description, title="Description", border_style="dim"))

    if result.signals:
        signal_text = "  ".join(f"[cyan]{k}[/cyan]" for k in sorted(result.signals))
        console.print(Panel(signal_text, title="Detected signals", border_style="dim"))

    if result.key_files:
        files = "\n".join(f"  • {path}" for path in result.key_files)
        console.print(Panel(files, title="Key files", border_style="dim"))

    if result.readme_excerpt:
        excerpt = result.readme_excerpt[:800]
        if len(result.readme_excerpt) > 800:
            excerpt += "\n…"
        console.print(Panel(excerpt, title="README excerpt", border_style="dim"))

    if result.file_tree_excerpt:
        console.print(Panel(
            result.file_tree_excerpt,
            title="File tree (sample)",
            border_style="dim",
        ))

    meta_parts = [f"Primary language: {result.primary_language or 'unknown'}"]
    if result.reference_index_built:
        meta_parts.append(f"Reference index: {result.reference_symbol_count:,} symbols")
    if saved_path:
        meta_parts.append(f"Saved → {saved_path}")
    console.print(f"[dim]{' · '.join(meta_parts)}[/dim]\n")


def _first_sentence(text: str, max_len: int = 140) -> str:
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


def _short_finding_title(title: str, max_len: int = 56) -> str:
    title = (title or "").strip()
    if len(title) <= max_len:
        return title
    return title[: max_len - 1].rstrip() + "…"


def display_repo_evaluation(result: RepoEvaluationResult, saved_path: Optional[Path] = None) -> None:
    """Render a compact radar-style repo evaluation scoreboard."""
    r = result.ratings
    risk = result.risk_level
    risk_style = _RISK_STYLE.get(risk, "white")
    border = "red" if risk in ("critical", "high") else ("yellow" if risk == "medium" else "green")
    n_crit = len(result.critical_vulnerabilities)
    n_sec = len(result.secrets_and_pii_risks)
    n_mods = len(result.module_reads)

    board = Table.grid(padding=(0, 2))
    board.add_column(justify="left")
    board.add_column(justify="left")
    board.add_row(
        Text(risk.upper(), style=risk_style),
        Text.from_markup(
            f"Overall [bold]{r.overall_grade}[/bold]  ·  "
            f"Security {r.security_grade}  ·  "
            f"Secrets {r.secrets_status}  ·  "
            f"PII {r.pii_status}"
        ),
    )
    board.add_row(
        "",
        Text(
            f"{n_crit} critical  ·  {n_sec} secrets/PII  ·  {n_mods} modules deep-read",
            style="dim",
        ),
    )
    so_what = _first_sentence(result.executive_summary)
    if so_what:
        board.add_row("", Text(so_what, style="italic"))

    console.print(
        Panel(
            board,
            title=f"[bold]EagleEye[/bold] · {result.repo} [dim]({result.branch})[/dim]",
            border_style=border,
            box=box.HEAVY,
            padding=(1, 2),
        )
    )

    # Compact WHAT / WHY / FLOW strip
    strip = Table.grid(padding=(0, 1))
    strip.add_column(style="bold cyan", width=6)
    strip.add_column()
    has_strip = False
    if result.what_it_is:
        strip.add_row("WHAT", _first_sentence(result.what_it_is, 110))
        has_strip = True
    if result.problem_solved:
        strip.add_row("WHY", _first_sentence(result.problem_solved, 110))
        has_strip = True
    if result.how_it_works:
        flow = result.how_it_works.strip().replace("\n", " ")
        strip.add_row("FLOW", flow[:160] + ("…" if len(flow) > 160 else ""))
        has_strip = True
    if has_strip:
        console.print(Panel(strip, border_style="dim", box=box.SIMPLE, padding=(0, 1)))

    if result.module_reads:
        mod_line = Text()
        mod_line.append("MODULES  ", style="bold")
        for i, m in enumerate(result.module_reads[:6]):
            if i:
                mod_line.append("  ")
            mod_line.append(m.module, style="cyan")
            if m.purpose:
                mod_line.append(f"·{_first_sentence(m.purpose, 36)}", style="dim")
        console.print(mod_line)
        console.print()

    if result.critical_vulnerabilities:
        console.print(Text("⚠  CRITICAL HITS", style="bold red"))
        for f in result.critical_vulnerabilities[:8]:
            loc = f"`{f.file}`" + (f":{f.line}" if f.line else "")
            console.print(
                f"  [red]◆[/red] [{f.severity.upper()}] "
                f"{_short_finding_title(f.title)}  [dim]{loc}[/dim]"
            )
        console.print()

    if result.secrets_and_pii_risks:
        console.print(Text("◇  SECRETS / PII", style="bold yellow"))
        for f in result.secrets_and_pii_risks[:8]:
            loc = f"`{f.file}`" if f.file else ""
            console.print(
                f"  [yellow]·[/yellow] [{f.severity.upper()}] "
                f"{_short_finding_title(f.title)}  [dim]{loc}[/dim]"
            )
        console.print()

    if result.recommendations:
        console.print(Text("NEXT", style="bold green"))
        shown = result.recommendations[:3]
        for i, rec in enumerate(shown, 1):
            console.print(f"  {i}. {_first_sentence(rec, 100)}")
        extra = len(result.recommendations) - len(shown)
        if extra > 0:
            console.print(f"  [dim]… +{extra} more → open HTML report[/dim]")
        console.print()

    if result.remediation_plan:
        console.print(Text("PLAN · fix the code", style="bold magenta"))
        for step in result.remediation_plan[:5]:
            files = ", ".join(f"`{p}`" for p in step.files[:3]) or "n/a"
            console.print(
                f"  [magenta]{step.priority}.[/magenta] "
                f"[{step.severity.upper()}] {step.title}"
            )
            console.print(f"     [dim]files[/dim]  {files}")
            console.print(
                f"     [dim]change[/dim] {_first_sentence(step.change_plan, 120)}"
            )
            if step.acceptance_check:
                console.print(
                    f"     [dim]check[/dim]  {_first_sentence(step.acceptance_check, 100)}"
                )
        extra = len(result.remediation_plan) - min(5, len(result.remediation_plan))
        if extra > 0:
            console.print(f"  [dim]… +{extra} steps → open HTML report[/dim]")
        console.print()

    if result.synthesis_failed:
        console.print("[yellow]Note: LLM synthesis skipped — deterministic findings only.[/yellow]")

    cov = result.coverage
    footer_bits: list[str] = []
    if cov:
        footer_bits.append(
            f"{cov.get('audit_scanned', '?')}/{cov.get('audit_eligible', '?')} audited"
        )
        if cov.get("modules_read") is not None:
            footer_bits.append(
                f"{cov.get('modules_read', 0)}/{cov.get('modules_planned', 0)} modules"
            )
            footer_bits.append(f"{cov.get('files_deep_read', 0)} files deep-read")
    if saved_path:
        html_hint = saved_path.with_suffix(".html") if saved_path.suffix == ".md" else saved_path
        footer_bits.append(f"Saved → {html_hint}")
    if footer_bits:
        console.print(f"[dim]{' · '.join(footer_bits)}[/dim]")
    console.print("[dim]Cockpit → reviews/index.html[/dim]\n")


def display_diagram(result: DiagramResult, saved_path: Optional[Path] = None) -> None:
    console.print(Panel(
        f"[bold]{result.title}[/bold]\n[dim]{result.description}[/dim]",
        title=f"[bold]Diagram: {result.diagram_type.replace('_', ' ').title()}[/bold]",
        border_style="magenta",
    ))
    # Print raw Mermaid with syntax highlighting
    syntax = Syntax(result.mermaid_source, "markdown", theme="monokai", word_wrap=True)
    console.print(syntax)
    if saved_path:
        console.print(f"\n[dim]Diagram saved → {saved_path}[/dim]")



def display_batch_summary(summaries: list[tuple[str, RepoSummaryResult, Optional[Path]]]) -> None:
    """Display a summary table for batch repo reads.

    summaries: list of (repo_full_name, summary_result, diagram_path_or_None)
    """
    table = Table(
        title="Batch Repo Analysis",
        box=box.ROUNDED,
        show_lines=True,
        expand=True,
    )
    table.add_column("#", width=4)
    table.add_column("Repo", style="cyan bold", max_width=30)
    table.add_column("Purpose", max_width=50)
    table.add_column("Stack", max_width=35)
    table.add_column("Diagram", width=8)

    for i, (repo_name, summary, diagram_path) in enumerate(summaries, 1):
        stack_str = ", ".join(summary.tech_stack[:4])
        diagram_indicator = "[green]✓[/green]" if diagram_path else "[dim]-[/dim]"
        table.add_row(
            str(i),
            repo_name.split("/")[-1],
            summary.purpose[:120],
            stack_str,
            diagram_indicator,
        )

    console.print(table)


# Approximate Sonnet 4.x pricing (USD per million tokens)
_PRICE_INPUT = 3.00
_PRICE_CACHE_WRITE = 3.75
_PRICE_CACHE_READ = 0.30
_PRICE_OUTPUT = 15.00


def display_token_usage(usage: TokenUsage) -> None:
    """Render a token usage breakdown panel after a command completes."""
    def _fmt(n: int) -> str:
        return f"{n:,}"

    # Cost with caching
    cost_actual = (
        usage.input_tokens * _PRICE_INPUT
        + usage.cache_creation_input_tokens * _PRICE_CACHE_WRITE
        + usage.cache_read_input_tokens * _PRICE_CACHE_READ
        + usage.output_tokens * _PRICE_OUTPUT
    ) / 1_000_000

    # Cost without caching (all input tokens at full price)
    cost_no_cache = (
        usage.uncached_equivalent_input * _PRICE_INPUT
        + usage.output_tokens * _PRICE_OUTPUT
    ) / 1_000_000

    saved = cost_no_cache - cost_actual

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Label", style="dim", min_width=28)
    table.add_column("Value", justify="right")

    table.add_row("Input (uncached)", f"[white]{_fmt(usage.input_tokens)}[/white] tokens")
    table.add_row("Cache write", f"[cyan]{_fmt(usage.cache_creation_input_tokens)}[/cyan] tokens")
    table.add_row("Cache read  [dim](10% cost)[/dim]", f"[green]{_fmt(usage.cache_read_input_tokens)}[/green] tokens")
    table.add_row("Output", f"[white]{_fmt(usage.output_tokens)}[/white] tokens")
    table.add_row("", "")
    table.add_row("Total input sent", f"[bold]{_fmt(usage.total_input)}[/bold] tokens")
    table.add_row(
        "Cache hit rate",
        f"[{'green' if usage.cache_hit_rate > 0.3 else 'yellow'}]{usage.cache_hit_rate:.0%}[/]",
    )
    table.add_row("", "")
    table.add_row("Est. cost (with cache)", f"[bold]${cost_actual:.4f}[/bold]")
    table.add_row("Est. cost (no cache)", f"[dim]${cost_no_cache:.4f}[/dim]")
    table.add_row(
        "Cache savings",
        f"[bold green]${saved:.4f}[/bold green]" if saved > 0 else "[dim]$0.0000[/dim]",
    )

    console.print(Panel(table, title="[bold]Token Usage[/bold]", border_style="dim"))


_CHANGE_TYPE_STYLE = {
    "added": "green",
    "removed": "red",
    "renamed": "yellow",
    "type_changed": "yellow",
    "modified": "cyan",
}


def display_schema_impact(result: SchemaImpactResult) -> None:
    if not result.changes:
        return

    n_consumers = sum(len(v) for v in result.consumers.values())
    summary = (
        f"{len(result.changes)} schema change(s) · "
        f"{n_consumers} downstream consumer(s) · "
        f"{result.files_analyzed} file(s) analyzed"
    )
    console.print(Panel(summary, title="[bold yellow]Schema Impact[/bold yellow]", border_style="yellow"))

    changes_table = Table(box=box.ROUNDED, show_lines=True, expand=True)
    changes_table.add_column("Change", width=13)
    changes_table.add_column("Field / Column", style="cyan")
    changes_table.add_column("Parent", style="dim", max_width=22)
    changes_table.add_column("Detail")
    changes_table.add_column("Consumers", width=10, justify="right")

    for change in result.changes:
        style = _CHANGE_TYPE_STYLE.get(change.change_type, "white")
        n = len(result.consumers.get(change.name, []))
        changes_table.add_row(
            Text(change.change_type.upper(), style=style),
            change.name,
            change.parent,
            change.detail,
            f"[red]{n}[/red]" if n else "[dim]—[/dim]",
        )
    console.print(changes_table)

    all_consumers = [
        (name, c)
        for name, cs in result.consumers.items()
        for c in cs
    ]
    if all_consumers:
        lines = []
        for _, c in all_consumers[:12]:
            kind = f"[dim]{c.consumer_kind}[/dim] " if c.consumer_kind else ""
            snippet = c.snippet.strip()[:90]
            lines.append(f"  {kind}[cyan]{c.file}:{c.line}[/cyan]  {snippet}")
        if len(all_consumers) > 12:
            lines.append(f"  [dim]… {len(all_consumers) - 12} more[/dim]")
        console.print(Panel("\n".join(lines), title="Downstream Consumers", border_style="yellow"))



def display_error(message: str) -> None:
    console.print(Panel(message, title="[bold red]Error[/bold red]", border_style="red"))


def display_file_manifest(manifest: list[dict], total_bytes: int) -> None:
    """Display a Rich table of files fetched, their sizes, and fetch status."""
    if not manifest:
        return

    _STATUS = {
        "ok":       ("[green]✓[/green]", "[green]Full content[/green]"),
        "truncated":("[yellow]~[/yellow]", "[yellow]Truncated[/yellow]"),
        "byte_cap": ("[red]✗[/red]",    "[red]Byte cap[/red]"),
        "file_cap": ("[dim]–[/dim]",    "[dim]File cap[/dim]"),
        "error":    ("[red]![/red]",    "[red]Fetch error[/red]"),
    }

    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold dim",
        padding=(0, 1),
    )
    table.add_column("", width=2, no_wrap=True)
    table.add_column("File", style="dim", no_wrap=False)
    table.add_column("Size", justify="right", width=9, no_wrap=True)
    table.add_column("Status", width=14, no_wrap=True)

    fetched = [m for m in manifest if m["status"] in ("ok", "truncated")]
    skipped = [m for m in manifest if m["status"] not in ("ok", "truncated")]

    for entry in fetched:
        icon, label = _STATUS[entry["status"]]
        kb = f"{entry['size'] / 1024:.1f} KB" if entry["size"] else "—"
        table.add_row(icon, entry["file"], kb, label)

    if skipped:
        table.add_section()
        for entry in skipped:
            icon, label = _STATUS[entry["status"]]
            kb = f"{entry['size'] / 1024:.1f} KB" if entry["size"] else "—"
            table.add_row(icon, entry["file"], kb, label)

    kb_total = total_bytes / 1024
    title = (
        f"[bold]Files read into context[/bold] — "
        f"[green]{len(fetched)}[/green] fetched · "
        f"[dim]{len(skipped)} skipped[/dim] · "
        f"[cyan]{kb_total:.1f} KB[/cyan] total"
    )
    console.print(Panel(table, title=title, border_style="dim", padding=(0, 1)))


def display_phase(name: str, source: str) -> None:
    """Blank line + bold phase header + dim code pointer, then a rule."""
    console.print()
    console.print(
        f"[bold cyan]◆[/bold cyan] [bold white]{name}[/bold white]"
        f"  [dim]← {source}[/dim]"
    )
    console.rule(style="dim cyan")


def display_phase_skipped(name: str, reason: str, source: str) -> None:
    """Blank line + dimmed phase header marked SKIPPED, with reason and code pointer."""
    console.print()
    console.print(
        f"[dim]◇ {name}[/dim]  [yellow]SKIPPED[/yellow]"
        f"  [dim]← {source}[/dim]"
    )
    console.print(f"  [dim italic]{reason}[/dim italic]")
    console.rule(style="dim")


def display_info(message: str) -> None:
    console.print(f"[dim]{message}[/dim]")


def display_success(message: str) -> None:
    console.print(f"[green]{message}[/green]")


def display_warning(message: str) -> None:
    console.print(f"[yellow]⚠[/yellow]  {message}")
