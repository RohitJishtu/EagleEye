"""Tests for optional lineage extra (M4)."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest


def test_import_analysis_does_not_load_db_lineage():
    mod = importlib.import_module("eagleeye.analysis")
    if hasattr(mod, "scan_diff"):
        del mod.scan_diff
    for name in list(sys.modules):
        if name.startswith("eagleeye.db_lineage"):
            del sys.modules[name]

    from eagleeye.analysis import scan_diff  # noqa: F401

    loaded = [m for m in sys.modules if m.startswith("eagleeye.db_lineage")]
    assert loaded == [], f"db_lineage loaded on scan_diff import: {loaded}"


def test_is_available_reflects_pandas():
    from eagleeye.lineage import is_available, missing_dependencies

    with patch("eagleeye.lineage._availability._MISSING", None):
        with patch("eagleeye.lineage._availability._check_import") as check:
            check.side_effect = lambda _mod, pkg, missing: missing.append(pkg)
            assert is_available() is False
            assert missing_dependencies() == ("pandas",)


def test_require_lineage_raises_without_pandas():
    from eagleeye.lineage import require_lineage

    with patch("eagleeye.lineage._availability._MISSING", ("pandas",)):
        with pytest.raises(ImportError, match=r"eagleeye\[lineage\]"):
            require_lineage(feature="test feature")


def test_extract_snowflake_usages_works_without_pandas():
    from eagleeye.lineage import extract_snowflake_usages

    with patch("eagleeye.lineage._availability._MISSING", ("pandas",)):
        extract = extract_snowflake_usages(
            diff="--- a/jobs/load.sql\n+++ b/jobs/load.sql\n+SELECT * FROM DB.SCHEMA.MY_TABLE",
            files={"jobs/load.sql": "SELECT * FROM DB.SCHEMA.MY_TABLE"},
        )
    assert any(u.table == "MY_TABLE" for u in extract.usages)


def test_registry_does_not_eager_load_snowflake():
    for name in list(sys.modules):
        if name.startswith("eagleeye.db_lineage"):
            del sys.modules[name]

    import eagleeye.db_lineage.registry as registry  # noqa: F401

    assert registry._defaults_loaded is False
    assert registry._PROVIDERS == {}


def test_get_provider_loads_snowflake():
    from eagleeye.db_lineage.registry import _PROVIDERS, get_provider

    provider = get_provider("snowflake")
    assert "snowflake" in _PROVIDERS
    assert provider is not None
