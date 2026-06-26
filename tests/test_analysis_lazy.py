"""Verify analysis package lazy imports (M0.2)."""

import importlib
import sys


def test_scan_diff_does_not_load_db_lineage():
    """Importing scan_diff must not eagerly load db_lineage."""
    # Fresh import of analysis subpackage only
    mod = importlib.import_module("eagleeye.analysis")
    if hasattr(mod, "scan_diff"):
        del mod.scan_diff
    for name in list(sys.modules):
        if name.startswith("eagleeye.db_lineage"):
            del sys.modules[name]

    from eagleeye.analysis import scan_diff  # noqa: F401

    loaded = [m for m in sys.modules if m.startswith("eagleeye.db_lineage")]
    assert loaded == [], f"db_lineage loaded on scan_diff import: {loaded}"


def test_snowflake_symbols_load_on_demand():
    """Snowflake lineage symbols load only when accessed."""
    for name in list(sys.modules):
        if (
            name.startswith("eagleeye.db_lineage")
            or name == "eagleeye.analysis.snowflake_lineage"
            or name == "eagleeye.lineage"
        ):
            del sys.modules[name]

    from eagleeye.analysis import extract_snowflake_usages

    assert callable(extract_snowflake_usages)
    loaded = [
        m
        for m in sys.modules
        if m.startswith("eagleeye.db_lineage") or m.startswith("eagleeye.lineage")
    ]
    assert loaded, "lineage or db_lineage should load on snowflake symbol access"
