from pathlib import Path

from eagleeye.reference_store import extract_dbt_yml

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_dbt_yml_finds_model_defs():
    content = (FIXTURES / "schema.yml").read_text()
    result = extract_dbt_yml(content, "models/schema.yml")
    names = [name for name, m in result if m.kind == "dbt.model_def"]
    assert "fct_account_health" in names
    assert "dim_account" in names


def test_extract_dbt_yml_finds_sources_by_table_name():
    content = (FIXTURES / "schema.yml").read_text()
    result = extract_dbt_yml(content, "models/schema.yml")
    names = [name for name, m in result if m.kind == "dbt.source"]
    assert "account" in names
    assert "opportunity" in names


def test_extract_dbt_yml_finds_sources_qualified():
    content = (FIXTURES / "schema.yml").read_text()
    result = extract_dbt_yml(content, "models/schema.yml")
    names = [name for name, m in result if m.kind == "dbt.source"]
    assert "salesforce.account" in names


def test_extract_dbt_yml_snippet_has_name_line():
    content = (FIXTURES / "schema.yml").read_text()
    result = extract_dbt_yml(content, "models/schema.yml")
    fct = next(m for name, m in result if name == "fct_account_health")
    assert "fct_account_health" in fct.snippet


from eagleeye.reference_store import extract_dbt_sql


def test_extract_dbt_sql_finds_ref():
    content = (FIXTURES / "model.sql").read_text()
    result = extract_dbt_sql(content, "models/marts/fct_renewal.sql")
    names = [name for name, m in result if m.kind == "dbt.ref"]
    assert "fct_account_health" in names


def test_extract_dbt_sql_finds_source():
    content = (FIXTURES / "model.sql").read_text()
    result = extract_dbt_sql(content, "models/marts/fct_renewal.sql")
    sources = [name for name, m in result if m.kind == "dbt.source"]
    assert "opportunity" in sources
    assert "salesforce.opportunity" in sources


def test_extract_dbt_sql_double_quotes():
    result = extract_dbt_sql('select * from {{ ref("x") }}', "models/x.sql")
    assert any(name == "x" and m.kind == "dbt.ref" for name, m in result)
