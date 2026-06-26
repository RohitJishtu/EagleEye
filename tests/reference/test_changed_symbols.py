from eagleeye.reference_store import extract_changed_symbols


def test_changed_symbols_collects_py_defs():
    files = {"src/etl.py": "def load_pipeline(cfg):\n    return cfg\n"}
    result = extract_changed_symbols(files)
    assert "load_pipeline" in result


def test_changed_symbols_collects_table_defs():
    files = {"ddl/schema.sql": "CREATE TABLE foo (x int);"}
    result = extract_changed_symbols(files)
    assert "FOO" in result


def test_changed_symbols_collects_dbt_model_defs():
    files = {"models/schema.yml": "models:\n  - name: fct_revenue\n"}
    result = extract_changed_symbols(files)
    assert "fct_revenue" in result


def test_changed_symbols_collects_js_defs():
    files = {"src/x.ts": "export function startServer() {}"}
    result = extract_changed_symbols(files)
    assert "startServer" in result


def test_changed_symbols_ignores_calls_and_imports():
    files = {"src/etl.py": "def a():\n    return load_other()\n"}
    result = extract_changed_symbols(files)
    assert "a" in result
    assert "load_other" not in result


def test_changed_symbols_handles_extractor_failure(monkeypatch):
    from eagleeye import reference_store as rs
    def boom(content, path):
        raise RuntimeError("nope")
    monkeypatch.setattr(rs, "_dispatch_extractor",
                        lambda p: boom if p.endswith(".py") else None)
    result = extract_changed_symbols({"x.py": "def y(): pass"})
    assert result == set()
