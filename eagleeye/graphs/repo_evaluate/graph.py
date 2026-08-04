"""LangGraph workflow for full repo evaluation (multi-module deep read by default)."""

from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from ...core.config import EagleEyeConfig, resolve_github_token
from ...core.models import ModuleReadResult, RepoEvaluationResult, RepoMap
from ...core.prompt_loader import get_prompt
from ...features.repo_auditor import AuditResult, run_audit
from ...integrations.anthropic.client import (
    _MODULE_READ_SCHEMA,
    _REPO_EVALUATION_SCHEMA,
    TokenUsage,
    _clean_json,
)
from ...integrations.github import GitHubAPIError, GitHubClient
from ...storage.maps import save_map
from ...workflows.repo_audit import fetch_file_contents, fetch_scannable_contents
from ...workflows.repo_evaluate.findings import (
    audit_to_eval_findings,
    build_remediation_plan,
    compute_ratings,
    merge_eval_findings,
    risk_level_from_findings,
)
from ...workflows.repo_evaluate.modules import (
    MAX_MODULE_FILE_BYTES,
    partition_modules,
)
from ...workflows.repo_evaluate.persist import save_evaluation
from ...workflows.repo_evaluate.prepare import (
    build_module_bundle,
    build_synthesis_bundle,
    build_synthesis_bundle_from_modules,
)
from ...workflows.repo_read.helpers import _MAX_FILE_BYTES, _select_key_files
from ...workflows.understand_build import build_repo_map_from_parts


class RepoEvaluateState(TypedDict):
    owner: str
    repo: str
    branch: Optional[str]
    scoped_path: Optional[str]
    no_llm: bool
    quick: bool
    include_data_dirs: bool
    api_key: str
    github_token: str
    model: str
    max_tokens: int
    auth_mode: str
    proxy_client_id: str
    proxy_client_secret: str
    proxy_url: str
    token_url: str
    scope: str
    repo_metadata: dict
    effective_branch: str
    readme: str
    file_tree: list
    repo_map: Optional[RepoMap]
    key_paths: list
    key_file_contents: dict
    audit_result: Optional[AuditResult]
    audit_files: list
    coverage: dict
    modules: list
    module_reads: list
    result: Optional[RepoEvaluationResult]
    saved_path: str
    token_usage: TokenUsage


def fetch_all(state: RepoEvaluateState) -> dict:
    from ...presentation.terminal import display_info, display_phase

    display_phase("Phase 1 · Fetching repo data", "graphs/repo_evaluate/graph.py")
    github = GitHubClient(state["github_token"])
    try:
        meta = github.get_repo_metadata(state["owner"], state["repo"])
        effective_branch = state.get("branch") or meta.get("default_branch", "main")
        readme = github.get_repo_readme(state["owner"], state["repo"])
        try:
            tree = github.get_repo_tree(state["owner"], state["repo"], effective_branch)
        except GitHubAPIError:
            tree = []
    finally:
        github.close()

    blob_paths = [item["path"] for item in tree if item.get("type") == "blob"]
    key_paths = _select_key_files(blob_paths)
    display_info(f"Fetched tree with {len(blob_paths)} files")
    return {
        "repo_metadata": meta,
        "effective_branch": effective_branch,
        "readme": readme,
        "file_tree": tree,
        "key_paths": key_paths,
    }


def build_map_and_audit(state: RepoEvaluateState) -> dict:
    from ...presentation.terminal import display_info, display_phase

    display_phase("Phase 2–3 · Repo map & priority audit", "graphs/repo_evaluate/graph.py")

    repo_map = build_repo_map_from_parts(
        state["owner"],
        state["repo"],
        state["effective_branch"],
        state["repo_metadata"],
        state["file_tree"],
        state["readme"],
    )
    save_map(repo_map)

    github = GitHubClient(state["github_token"])
    try:
        file_contents, coverage = fetch_scannable_contents(
            github,
            state["owner"],
            state["repo"],
            state["effective_branch"],
            path=state.get("scoped_path"),
            key_paths=state["key_paths"],
        )
        key_file_contents = {
            p: c[:_MAX_FILE_BYTES]
            for p, c in fetch_file_contents(
                github,
                state["owner"],
                state["repo"],
                state["effective_branch"],
                state["key_paths"],
            ).items()
        }
    finally:
        github.close()

    audit = run_audit(file_contents, repo=f"{state['owner']}/{state['repo']}")
    cov = coverage.as_dict()
    cov["key_files_fetched"] = len(key_file_contents)
    cov["llm_excluded_prefixes"] = [] if state.get("include_data_dirs") else [
        "data/", "out/", "fixtures/", "tests/"
    ]
    display_info(audit.summary())

    return {
        "repo_map": repo_map,
        "audit_result": audit,
        "audit_files": list(file_contents.keys()),
        "coverage": cov,
        "key_file_contents": key_file_contents,
    }


def partition_modules_node(state: RepoEvaluateState) -> dict:
    from ...presentation.terminal import display_info, display_phase

    if state.get("no_llm") or state.get("quick"):
        return {"modules": [], "module_reads": []}

    display_phase("Phase 3b · Partitioning modules", "graphs/repo_evaluate/graph.py")
    plans = partition_modules(
        state["file_tree"],
        scoped_path=state.get("scoped_path"),
        include_data_dirs=state.get("include_data_dirs", False),
    )
    coverage = dict(state.get("coverage") or {})
    coverage["modules_planned"] = len(plans)
    coverage["modules_read"] = 0
    coverage["files_deep_read"] = 0
    names = ", ".join(p.name for p in plans) or "(none)"
    display_info(f"Planned {len(plans)} module(s): {names}")
    return {
        "modules": [p.as_dict() for p in plans],
        "module_reads": [],
        "coverage": coverage,
    }


def deep_read_modules(state: RepoEvaluateState) -> dict:
    from langchain_core.messages import HumanMessage

    from ...presentation.terminal import display_info, display_phase
    from .._shared import accumulate_usage, make_cached_system_message, make_content_block, make_llm

    if state.get("no_llm") or state.get("quick"):
        return {}

    modules = state.get("modules") or []
    if not modules:
        display_phase("Phase 4 · Deep-read skipped (no modules)", "graphs/repo_evaluate/graph.py")
        return {"module_reads": []}

    display_phase("Phase 4 · Deep-reading modules", "graphs/repo_evaluate/graph.py")
    llm = make_llm(state)
    system = make_cached_system_message(get_prompt("utils.repo_evaluate_module"))
    usage = state.get("token_usage") or TokenUsage()
    module_reads: list[ModuleReadResult] = []
    files_deep_read = 0

    github = GitHubClient(state["github_token"])
    try:
        for idx, mod in enumerate(modules, start=1):
            name = mod["name"]
            paths = mod.get("paths") or []
            display_info(f"Deep-reading module {idx}/{len(modules)}: {name}/ ({len(paths)} files)")
            raw_contents = fetch_file_contents(
                github,
                state["owner"],
                state["repo"],
                state["effective_branch"],
                paths,
            )
            contents = {p: c[:MAX_MODULE_FILE_BYTES] for p, c in raw_contents.items()}
            files_deep_read += len(contents)
            if not contents:
                continue

            bundle = build_module_bundle(name, contents)
            user_blocks = [
                make_content_block(bundle, cache=True),
                make_content_block(
                    f"Respond with valid JSON exactly matching this schema:\n{_MODULE_READ_SCHEMA}"
                ),
            ]
            try:
                response = llm.invoke([system, HumanMessage(content=user_blocks)])
                accumulate_usage(usage, response.response_metadata)
                raw = (
                    response.content
                    if isinstance(response.content, str)
                    else str(response.content)
                )
                read = ModuleReadResult.model_validate_json(_clean_json(raw))
                if not read.module:
                    read.module = name
                if not read.files_read:
                    read.files_read = list(contents.keys())
                module_reads.append(read)
            except (ValueError, ValidationError, RuntimeError) as exc:
                display_info(f"Warning: module deep-read failed for {name} — {exc}")
                module_reads.append(
                    ModuleReadResult(
                        module=name,
                        purpose=f"(Deep-read failed: {exc})",
                        files_read=list(contents.keys()),
                        gotchas=["Module LLM read failed; using file list only."],
                    )
                )
    finally:
        github.close()

    coverage = dict(state.get("coverage") or {})
    coverage["modules_planned"] = len(modules)
    coverage["modules_read"] = len(module_reads)
    coverage["files_deep_read"] = files_deep_read
    display_info(f"Completed {len(module_reads)} module deep-read(s), {files_deep_read} files")
    return {"module_reads": module_reads, "coverage": coverage, "token_usage": usage}


def _deterministic_result(
    state: RepoEvaluateState,
    *,
    summary: str,
    problem: str,
    confidence: list[str],
) -> RepoEvaluationResult:
    audit = state["audit_result"]
    repo_map = state["repo_map"]
    assert audit is not None and repo_map is not None
    det_findings = audit_to_eval_findings(audit)
    det_crit, det_sec = merge_eval_findings(det_findings, [], [])
    ratings = compute_ratings(audit, repo_map, state.get("coverage") or {})
    risk = risk_level_from_findings(det_crit, audit)
    return RepoEvaluationResult(
        repo=f"{state['owner']}/{state['repo']}",
        branch=state["effective_branch"],
        scoped_path=state.get("scoped_path"),
        executive_summary=summary,
        what_it_is=(
            repo_map.description
            or repo_map.readme_excerpt[:500]
            or "See README excerpt in RepoMap."
        ),
        problem_solved=problem,
        how_it_works=(
            f"Signals: {', '.join(repo_map.signals) or 'none'}. "
            f"Key files: {', '.join(repo_map.key_files[:5])}."
        ),
        critical_vulnerabilities=det_crit,
        secrets_and_pii_risks=det_sec,
        recommendations=[f.fix for f in det_crit[:5]],
        remediation_plan=build_remediation_plan(det_crit + det_sec),
        risk_level=risk,  # type: ignore[arg-type]
        ratings=ratings,
        confidence_notes=confidence,
        coverage=state.get("coverage") or {},
        synthesis_failed=True,
        module_reads=list(state.get("module_reads") or []),
    )


def synthesize(state: RepoEvaluateState) -> dict:
    from langchain_core.messages import HumanMessage

    from ...presentation.terminal import display_info, display_phase
    from .._shared import accumulate_usage, make_cached_system_message, make_content_block, make_llm

    owner, repo = state["owner"], state["repo"]
    repo_slug = f"{owner}/{repo}"
    audit = state["audit_result"]
    repo_map = state["repo_map"]
    coverage = dict(state.get("coverage") or {})
    scoped = state.get("scoped_path")
    module_reads: list[ModuleReadResult] = list(state.get("module_reads") or [])

    assert audit is not None and repo_map is not None

    det_findings = audit_to_eval_findings(audit)
    det_crit, det_sec = merge_eval_findings(det_findings, [], [])
    ratings = compute_ratings(audit, repo_map, coverage)
    risk = risk_level_from_findings(det_crit, audit)

    if state.get("no_llm"):
        display_phase("Phase 5 · Skipped (no LLM)", "graphs/repo_evaluate/graph.py")
        result = _deterministic_result(
            state,
            summary=(
                f"Deterministic evaluation of {repo_slug}. {audit.summary()} "
                "LLM synthesis skipped (--no-llm)."
            ),
            problem=(
                "(LLM synthesis skipped — run without --no-llm for narrative assessment.)"
            ),
            confidence=["LLM synthesis was skipped."],
        )
        return {"result": result, "token_usage": state.get("token_usage") or TokenUsage()}

    display_phase("Phase 5 · Synthesis", "graphs/repo_evaluate/graph.py")
    display_info("Generating evaluation report with Claude…")

    if state.get("quick") or not module_reads:
        bundle = build_synthesis_bundle(
            repo_map,
            state["readme"],
            audit,
            state["key_file_contents"],
            coverage,
            scoped,
            include_data_dirs=state.get("include_data_dirs", False),
        )
        if not module_reads and not state.get("quick"):
            display_info("No module reads — falling back to key-file synthesis bundle")
    else:
        bundle = build_synthesis_bundle_from_modules(
            repo_map,
            state["readme"],
            audit,
            module_reads,
            coverage,
            scoped,
            include_data_dirs=state.get("include_data_dirs", False),
        )

    llm = make_llm(state)
    system = make_cached_system_message(get_prompt("utils.repo_evaluate_synthesis"))
    user_blocks = [
        make_content_block(bundle, cache=True),
        make_content_block(
            f"Respond with valid JSON exactly matching this schema:\n{_REPO_EVALUATION_SCHEMA}"
        ),
    ]

    usage = state.get("token_usage") or TokenUsage()
    synthesis_failed = False
    llm_result: Optional[RepoEvaluationResult] = None

    try:
        response = llm.invoke([system, HumanMessage(content=user_blocks)])
        accumulate_usage(usage, response.response_metadata)
        raw = response.content if isinstance(response.content, str) else str(response.content)
        llm_result = RepoEvaluationResult.model_validate_json(_clean_json(raw))
    except (ValueError, ValidationError, RuntimeError) as exc:
        synthesis_failed = True
        display_info(f"Warning: synthesis failed — {exc}")

    if llm_result is None:
        result = RepoEvaluationResult(
            repo=repo_slug,
            branch=state["effective_branch"],
            scoped_path=scoped,
            executive_summary=f"Partial evaluation of {repo_slug}. {audit.summary()}",
            what_it_is=repo_map.description or "See RepoMap.",
            problem_solved="(Synthesis failed.)",
            how_it_works=f"Signals: {', '.join(repo_map.signals) or 'none'}.",
            critical_vulnerabilities=det_crit,
            secrets_and_pii_risks=det_sec,
            recommendations=[f.fix for f in det_crit[:5]],
            remediation_plan=build_remediation_plan(det_crit + det_sec),
            risk_level=risk,  # type: ignore[arg-type]
            ratings=ratings,
            confidence_notes=["LLM synthesis failed — showing deterministic findings only."],
            coverage=coverage,
            synthesis_failed=True,
            module_reads=module_reads,
        )
        return {"result": result, "token_usage": usage}

    crit, sec = merge_eval_findings(
        det_findings,
        llm_result.critical_vulnerabilities,
        llm_result.secrets_and_pii_risks,
    )
    merged_ratings = ratings.model_copy(update={
        "documentation_score": (
            llm_result.ratings.documentation_score or ratings.documentation_score
        ),
        "testability_score": (
            llm_result.ratings.testability_score or ratings.testability_score
        ),
        "maintainability_score": (
            llm_result.ratings.maintainability_score or ratings.maintainability_score
        ),
        "rating_notes": ratings.rating_notes + (llm_result.ratings.rating_notes or []),
    })
    final_risk = llm_result.risk_level
    if audit.critical_count > 0 and final_risk in ("low", "medium"):
        final_risk = "high"

    plan = list(llm_result.remediation_plan or [])
    if not plan:
        plan = build_remediation_plan(crit + sec)

    result = RepoEvaluationResult(
        repo=repo_slug,
        branch=state["effective_branch"],
        scoped_path=scoped,
        executive_summary=llm_result.executive_summary,
        what_it_is=llm_result.what_it_is,
        problem_solved=llm_result.problem_solved,
        how_it_works=llm_result.how_it_works,
        critical_vulnerabilities=crit,
        secrets_and_pii_risks=sec,
        future_scope_stated=llm_result.future_scope_stated,
        future_scope_inferred=llm_result.future_scope_inferred,
        recommendations=llm_result.recommendations,
        remediation_plan=plan,
        risk_level=final_risk,
        ratings=merged_ratings,
        confidence_notes=llm_result.confidence_notes,
        coverage=coverage,
        synthesis_failed=synthesis_failed,
        module_reads=module_reads,
    )
    return {"result": result, "token_usage": usage}


def persist_evaluation(state: RepoEvaluateState) -> dict:
    from ...presentation.terminal import display_info, display_phase

    display_phase("Phase 6 · Saving evaluation", "graphs/repo_evaluate/graph.py")
    result = state["result"]
    assert result is not None
    path = save_evaluation(
        state["owner"],
        state["repo"],
        result,
        token_usage=state.get("token_usage"),
    )
    display_info(f"Evaluation saved to {path}")
    try:
        from ...presentation.html.eval_report import process as _generate_html
        html_path = _generate_html(path)
        display_info(f"HTML report  → {html_path}")
    except Exception as _e:
        display_info(f"Warning: could not generate HTML report — {_e}")

    try:
        from ...presentation.html.dashboard import build_dashboard
        build_dashboard()
        display_info("Cockpit updated → reviews/index.html")
    except Exception:
        pass

    return {"saved_path": str(path)}


def _build_graph():
    g = StateGraph(RepoEvaluateState)
    g.add_node("fetch_all", fetch_all)
    g.add_node("build_map_and_audit", build_map_and_audit)
    g.add_node("partition_modules", partition_modules_node)
    g.add_node("deep_read_modules", deep_read_modules)
    g.add_node("synthesize", synthesize)
    g.add_node("persist_evaluation", persist_evaluation)
    g.set_entry_point("fetch_all")
    g.add_edge("fetch_all", "build_map_and_audit")
    g.add_edge("build_map_and_audit", "partition_modules")
    g.add_edge("partition_modules", "deep_read_modules")
    g.add_edge("deep_read_modules", "synthesize")
    g.add_edge("synthesize", "persist_evaluation")
    g.add_edge("persist_evaluation", END)
    return g.compile()


_graph = _build_graph()


def run_repo_evaluate_graph(
    owner: str,
    repo: str,
    config: EagleEyeConfig,
    branch: Optional[str] = None,
    scoped_path: Optional[str] = None,
    no_llm: bool = False,
    quick: bool = False,
    include_data_dirs: bool = False,
) -> tuple[RepoEvaluationResult, TokenUsage, str]:
    initial: RepoEvaluateState = {
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "scoped_path": scoped_path,
        "no_llm": no_llm,
        "quick": quick,
        "include_data_dirs": include_data_dirs,
        "api_key": config.anthropic_api_key,
        "github_token": resolve_github_token(owner, config),
        "model": config.model,
        "max_tokens": config.max_tokens,
        "auth_mode": config.auth_mode,
        "proxy_client_id": config.proxy_client_id,
        "proxy_client_secret": config.proxy_client_secret,
        "proxy_url": config.proxy_url,
        "token_url": config.token_url,
        "scope": config.scope,
        "repo_metadata": {},
        "effective_branch": "",
        "readme": "",
        "file_tree": [],
        "repo_map": None,
        "key_paths": [],
        "key_file_contents": {},
        "audit_result": None,
        "audit_files": [],
        "coverage": {},
        "modules": [],
        "module_reads": [],
        "result": None,
        "saved_path": "",
        "token_usage": TokenUsage(),
    }
    final = _graph.invoke(initial)
    return final["result"], final["token_usage"], final["saved_path"]
