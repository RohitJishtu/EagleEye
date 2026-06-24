"""Pre-compute structural analysis and slice typed agent inputs."""

from __future__ import annotations

from dataclasses import replace as _dc_replace

from ...analysis import (
    compute_blast_radius,
    compute_edp_extract,
    compute_feature_store_extract,
    compute_schema_impact,
    compute_test_coverage,
    extract_snowflake_usages,
    format_as_markdown,
    format_edp_impact_markdown,
    format_feature_store_markdown,
    format_schema_impact_markdown,
    format_security_markdown,
    format_snowflake_lineage_markdown,
    format_test_coverage_markdown,
    scan_diff,
)
from ...presentation.terminal import display_info, display_phase
from ...core.models import MultiAgentReviewInput
from eagleeye.storage.reference import (
    extract_changed_symbols as _ref_changed_symbols,
    load_index as _load_ref_index,
    search_indexes as _search_ref_indexes,
)
from ..agent_inputs import slice_all
from .state import MultiAgentReviewState


def prepare_agent_input(state: MultiAgentReviewState) -> dict:
    display_phase(
        "Phase 4 · Pre-computing structural analysis",
        "graphs/multi_agent/prepare.py → prepare_agent_input",
    )
    display_info(
        "Pre-computing: blast radius, schema, Snowflake lineage, EDP, feature store, tests, security…"
    )

    diff = state["diff"]
    files = state["full_file_contents"]
    file_list = state["file_list"]

    sd = state.get("structural_diff")
    blast = compute_blast_radius(diff, files, structural_diff=sd)
    structural_md = ""
    if sd is not None:
        from ...analysis.symbol_diff import format_as_markdown as _format_sd
        structural_md = _format_sd(sd)
    schema = compute_schema_impact(diff, files)
    test_cov = compute_test_coverage(diff, files, file_list)
    sec = scan_diff(diff)
    sf_lineage = extract_snowflake_usages(diff, files)
    edp_extract = compute_edp_extract(diff, files)
    feature_store_extract = compute_feature_store_extract(diff, files)

    from ...lineage import infer_pr_lineage

    infer_pr_lineage(sf_lineage.usages)

    agent_input = MultiAgentReviewInput(
        diff=diff,
        pr_metadata=state["pr_metadata"],
        file_list=file_list,
        full_file_contents=files,
        blast_radius_md=(
            f"{structural_md}\n\n{format_as_markdown(blast)}"
            if structural_md
            else format_as_markdown(blast)
        ),
        schema_impact_md=format_schema_impact_markdown(schema),
        test_coverage_md=format_test_coverage_markdown(test_cov),
        security_scan_md=format_security_markdown(sec),
        snowflake_lineage_md=format_snowflake_lineage_markdown(sf_lineage),
        edp_impact_md=format_edp_impact_markdown(edp_extract),
        feature_store_md=format_feature_store_markdown(feature_store_extract),
        schema_impact_result=schema,
        max_file_bytes=state.get("max_file_bytes", 10_000),
    )
    slices = slice_all(agent_input)

    ref_repos = state.get("reference_repos") or []
    reference_matches_md = ""
    if ref_repos:
        indexes = []
        for spec in ref_repos:
            parts = spec.split("/", 1)
            if len(parts) != 2:
                continue
            try:
                idx = _load_ref_index(parts[0], parts[1])
            except Exception as exc:
                display_info(f"Reference index for {spec} skipped: {exc}")
                continue
            if idx is not None:
                indexes.append(idx)
        if indexes:
            try:
                changed = _ref_changed_symbols(files)
                reference_matches_md = _search_ref_indexes(indexes, changed)
            except Exception as exc:
                display_info(f"Reference search skipped: {exc}")

    slices["reference_agent_input"] = _dc_replace(
        slices["reference_agent_input"],
        reference_matches_md=reference_matches_md,
    )

    display_phase(
        "Phase 5 · Running specialist agents in parallel",
        "graphs/multi_agent/nodes.py → node_pr/schema/lineage/reference/arch_drift_agent",
    )
    return {"agent_input": agent_input, "schema_impact": schema, **slices}
