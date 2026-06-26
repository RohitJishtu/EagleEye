import json

from eagleeye.reference_store import (
    Match,
    ReferenceIndex,
    SCHEMA_VERSION,
    _dispatch_extractor,
    extract_py,
    extract_sql,
    extract_dbt_yml,
    extract_dbt_sql,
    extract_js,
    extract_ts,
    load_index,
    save_index,
)


def test_dispatch_py_returns_extract_py():
    assert _dispatch_extractor("src/x.py") is extract_py


def test_dispatch_sql_outside_models():
    assert _dispatch_extractor("ddl/schema.sql") is extract_sql


def test_dispatch_sql_under_models_uses_dbt():
    assert _dispatch_extractor("models/marts/fct.sql") is extract_dbt_sql


def test_dispatch_yml_under_models_uses_dbt():
    assert _dispatch_extractor("models/schema.yml") is extract_dbt_yml


def test_dispatch_yml_outside_models_returns_none():
    assert _dispatch_extractor(".github/workflows/ci.yml") is None


def test_dispatch_jsx_uses_js():
    assert _dispatch_extractor("src/app.jsx") is extract_js


def test_dispatch_tsx_uses_ts():
    assert _dispatch_extractor("src/app.tsx") is extract_ts


def test_dispatch_unknown_extension_returns_none():
    assert _dispatch_extractor("README.md") is None


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("eagleeye.reference_store.INDEX_DIR", tmp_path)
    idx = ReferenceIndex(
        owner="org", repo="repo", ref="main",
        built_at="2026-05-18T00:00:00Z", files_indexed=1,
        index={"foo": [Match("a.py", 1, "py.def", "def foo():")]},
    )
    save_index(idx)
    loaded = load_index("org", "repo")
    assert loaded is not None
    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.index["foo"][0].kind == "py.def"


def test_load_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("eagleeye.reference_store.INDEX_DIR", tmp_path)
    assert load_index("org", "missing") is None


def test_load_old_schema_returns_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("eagleeye.reference_store.INDEX_DIR", tmp_path)
    p = tmp_path / "org-repo" / "index.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"schema_version": 1, "owner": "org", "repo": "repo"}))
    assert load_index("org", "repo") is None
    err = capsys.readouterr().err
    assert "rebuild" in err.lower()
