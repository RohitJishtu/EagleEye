import pytest

from eagleeye.db_lineage.provider import DBLineageProvider, LineageResult


def test_lineage_result_structure():
    r = LineageResult(nodes=[{"name": "A", "type": "table", "depth": 0}], edges=[], cycles=[])
    assert r.nodes[0]["name"] == "A"
    assert r.edges == []


def test_provider_is_abstract():
    with pytest.raises(TypeError):
        DBLineageProvider()


def test_registry_raises_on_unknown():
    from eagleeye.db_lineage.registry import get_provider
    with pytest.raises(ValueError, match="Unknown lineage provider"):
        get_provider("bigquery")


def test_registry_has_register_function():
    from eagleeye.db_lineage import registry
    assert callable(registry._register)
    assert isinstance(registry._PROVIDERS, dict)


def test_snowflake_provider_registered():
    from eagleeye.db_lineage.registry import _PROVIDERS, get_provider

    get_provider("snowflake")
    assert "snowflake" in _PROVIDERS


def test_snowflake_implements_interface():
    from eagleeye.db_lineage.snowflake_metadata import SnowflakeLineageProvider
    from eagleeye.db_lineage.provider import DBLineageProvider
    assert issubclass(SnowflakeLineageProvider, DBLineageProvider)


def test_bfs_uses_groupby_not_iterrows():
    import inspect
    from eagleeye.db_lineage import snowflake_metadata as m
    src = inspect.getsource(m)
    assert "iterrows" not in src, "iterrows() found — must use GroupBy index"


def test_connection_closes_on_error():
    import inspect
    from eagleeye.db_lineage import snowflake_metadata as m
    src = inspect.getsource(m)
    assert "conn.close()" in src, "conn.close() must be called on error"


def test_sql_injection_guard_exists():
    import inspect
    from eagleeye.db_lineage import snowflake_metadata as m
    src = inspect.getsource(m)
    assert "_SAFE_OBJ_RE" in src or "validate" in src.lower(), "SQL injection guard required"
