from pathlib import Path

from eagleeye.reference_store import extract_sql

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_sql_finds_create_table():
    content = (FIXTURES / "sample.sql").read_text()
    result = extract_sql(content, "schema.sql")
    names = [name for name, m in result if m.kind == "sql.table_def"]
    assert "ANALYTICS.FCT_ORDERS" in names


def test_extract_sql_finds_table_refs_in_from():
    content = (FIXTURES / "sample.sql").read_text()
    result = extract_sql(content, "schema.sql")
    refs = [name for name, m in result if m.kind == "sql.table_ref"]
    assert "ANALYTICS.DIM_CUSTOMERS" in refs


def test_extract_sql_finds_table_refs_in_join():
    content = (FIXTURES / "sample.sql").read_text()
    result = extract_sql(content, "schema.sql")
    refs = [name for name, m in result if m.kind == "sql.table_ref"]
    assert "ANALYTICS.FCT_ORDERS" in refs


def test_extract_sql_finds_table_refs_in_insert_into():
    content = (FIXTURES / "sample.sql").read_text()
    result = extract_sql(content, "schema.sql")
    refs = [name for name, m in result if m.kind == "sql.table_ref"]
    assert "ANALYTICS.AUDIT_LOG" in refs


def test_extract_sql_normalises_to_uppercase():
    result = extract_sql("select * from lowercase_table;", "x.sql")
    refs = [name for name, m in result if m.kind == "sql.table_ref"]
    assert "LOWERCASE_TABLE" in refs


def test_extract_sql_falls_back_on_jinja():
    content = "select * from {{ var('schema') }}.foo where x = 1"
    result = extract_sql(content, "x.sql")
    refs = [name for name, m in result if m.kind == "sql.table_ref"]
    assert any("FOO" in r for r in refs)
