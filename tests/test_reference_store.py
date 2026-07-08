"""Sanity tests for the reference_store public surface.

The full extractor, dispatch, build, save/load, search, and changed-symbol
coverage lives in tests/reference/. This file keeps a couple of smoke tests
at the top-level path so a `pytest tests/test_reference_store.py` invocation
still exercises the module.
"""
from eagleeye.reference_store import (
    Match,
    ReferenceIndex,
    SCHEMA_VERSION,
    build_index,
    extract_changed_symbols,
    extract_py,
    load_index,
    save_index,
    search_indexes,
)


def test_extract_py_finds_def_and_call():
    result = extract_py(
        "def load_feature_groups(c):\n    return compute_score(c)\n",
        "x.py",
    )
    by_kind = {(name, m.kind) for name, m in result}
    assert ("load_feature_groups", "py.def") in by_kind
    assert ("compute_score", "py.call") in by_kind


def test_save_load_roundtrip(tmp_path, monkeypatch):
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


def test_search_indexes_returns_markdown_when_hit():
    idx = ReferenceIndex(
        owner="org", repo="repo", ref="main",
        built_at="2026-05-18T00:00:00Z", files_indexed=1,
        index={"foo": [Match("a.py", 1, "py.call", "foo()")]},
    )
    md = search_indexes([idx], {"foo"})
    assert "org/repo" in md
    assert "foo" in md
    assert "py.call" in md


def test_search_indexes_returns_empty_when_no_hit():
    idx = ReferenceIndex(
        owner="org", repo="repo", ref="main",
        built_at="2026-05-18T00:00:00Z", files_indexed=0,
    )
    assert search_indexes([idx], {"absent"}) == ""


def test_extract_changed_symbols_returns_defs_only():
    files = {"x.py": "def a(): pass\n", "schema.sql": "CREATE TABLE t (x int);"}
    result = extract_changed_symbols(files)
    assert "a" in result
    assert "T" in result


def test_build_index_smoke():
    from unittest.mock import MagicMock
    g = MagicMock()
    g.get_repo_tree.return_value = [
        {"path": "src/main.py", "type": "blob", "size": 50},
    ]
    g.get_file_content.side_effect = (
        lambda owner, repo, path, ref=None: "def main(): pass\n"
    )
    idx = build_index("org", "repo", g)
    assert idx.schema_version == SCHEMA_VERSION
    assert idx.files_indexed == 1
    assert "main" in idx.index
