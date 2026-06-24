"""Structural code analysis utilities."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "compute_blast_radius",
    "format_as_markdown",
    "SchemaImpactResult",
    "compute_schema_impact",
    "format_schema_impact_markdown",
    "compute_test_coverage",
    "format_test_coverage_markdown",
    "scan_diff",
    "format_security_markdown",
    "FeatureStoreExtract",
    "compute_feature_store_extract",
    "format_feature_store_markdown",
    "EDPExtract",
    "compute_edp_extract",
    "format_edp_impact_markdown",
    "LineageInfo",
    "SnowflakeObjectUsage",
    "SnowflakeUsageExtract",
    "extract_snowflake_usages",
    "format_snowflake_lineage_markdown",
    "resolve_lineage",
]

# Public name -> (submodule, attribute in submodule)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "compute_blast_radius": ("blast_radius", "compute_blast_radius"),
    "format_as_markdown": ("blast_radius", "format_as_markdown"),
    "SchemaImpactResult": ("schema_impact", "SchemaImpactResult"),
    "compute_schema_impact": ("schema_impact", "compute_schema_impact"),
    "format_schema_impact_markdown": ("schema_impact", "format_as_markdown"),
    "compute_test_coverage": ("test_coverage", "compute_test_coverage"),
    "format_test_coverage_markdown": ("test_coverage", "format_as_markdown"),
    "scan_diff": ("security_scan", "scan_diff"),
    "format_security_markdown": ("security_scan", "format_as_markdown"),
    "FeatureStoreExtract": ("feature_store", "FeatureStoreExtract"),
    "compute_feature_store_extract": ("feature_store", "compute_feature_store_extract"),
    "format_feature_store_markdown": ("feature_store", "format_as_markdown"),
    "EDPExtract": ("edp_impact", "EDPExtract"),
    "compute_edp_extract": ("edp_impact", "compute_edp_extract"),
    "format_edp_impact_markdown": ("edp_impact", "format_as_markdown"),
    "LineageInfo": ("snowflake_lineage", "LineageInfo"),
    "SnowflakeObjectUsage": ("snowflake_lineage", "SnowflakeObjectUsage"),
    "SnowflakeUsageExtract": ("snowflake_lineage", "SnowflakeUsageExtract"),
    "extract_snowflake_usages": ("snowflake_lineage", "extract_snowflake_usages"),
    "format_snowflake_lineage_markdown": ("snowflake_lineage", "format_as_markdown"),
    "resolve_lineage": ("snowflake_lineage", "resolve_lineage"),
}

_OPTIONAL_MODULES = frozenset({"blast_radius"})


def __getattr__(name: str) -> Any:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _LAZY_IMPORTS[name]
    try:
        module = importlib.import_module(f".{module_name}", __name__)
    except ImportError as exc:
        if module_name in _OPTIONAL_MODULES:
            raise AttributeError(
                f"module {__name__!r} has no attribute {name!r}"
            ) from exc
        raise
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
