from unittest.mock import MagicMock

from eagleeye.reference_store import build_index


def _mock_github(tree, contents):
    g = MagicMock()
    g.get_repo_tree.return_value = tree
    g.get_file_content.side_effect = lambda owner, repo, path, ref=None: contents.get(path, "")
    return g


def test_build_index_walks_tree_and_dispatches():
    tree = [
        {"path": "src/etl.py",   "type": "blob", "size": 100},
        {"path": "ddl/schema.sql", "type": "blob", "size": 80},
        {"path": "models/fct.sql", "type": "blob", "size": 90},
        {"path": "models/schema.yml", "type": "blob", "size": 60},
        {"path": "src/app.ts",   "type": "blob", "size": 50},
        {"path": "README.md",    "type": "blob", "size": 10},
        {"path": "node_modules/x.js", "type": "blob", "size": 1},
    ]
    contents = {
        "src/etl.py": "def run_etl(): pass\n",
        "ddl/schema.sql": "CREATE TABLE foo (x int);",
        "models/fct.sql": "select * from {{ ref('upstream_model') }}",
        "models/schema.yml": "models:\n  - name: my_model\n",
        "src/app.ts": "export function bootstrap() { return 1; }\n",
    }
    g = _mock_github(tree, contents)

    idx = build_index("org", "repo", g)

    assert idx.owner == "org"
    assert idx.repo == "repo"
    assert idx.schema_version == 2
    assert idx.files_indexed == 5
    assert "run_etl" in idx.index
    assert "FOO" in idx.index
    assert "upstream_model" in idx.index
    assert "my_model" in idx.index
    assert "bootstrap" in idx.index


def test_build_index_skips_oversize():
    tree = [{"path": "big.py", "type": "blob", "size": 2_000_000}]
    g = _mock_github(tree, {"big.py": "def x(): pass\n"})
    idx = build_index("org", "repo", g)
    assert idx.files_indexed == 0


def test_build_index_caps_matches_per_name():
    files = [{"path": f"f{i}.py", "type": "blob", "size": 30} for i in range(60)]
    contents = {f"f{i}.py": "def common(): pass\n" for i in range(60)}
    g = _mock_github(files, contents)
    idx = build_index("org", "repo", g)
    assert len(idx.index["common"]) == 50


def test_build_index_continues_on_extractor_error(monkeypatch):
    tree = [
        {"path": "ok.py", "type": "blob", "size": 30},
        {"path": "bad.py", "type": "blob", "size": 30},
    ]
    contents = {"ok.py": "def ok(): pass\n", "bad.py": "def bad(): pass\n"}
    g = _mock_github(tree, contents)

    from eagleeye import reference_store as rs
    orig = rs.extract_py
    def patched(content, path):
        if path == "bad.py":
            raise RuntimeError("boom")
        return orig(content, path)
    monkeypatch.setattr(rs, "extract_py", patched)
    monkeypatch.setattr(rs, "_dispatch_extractor",
                        lambda p: patched if p.endswith(".py") else None)

    idx = build_index("org", "repo", g)
    assert "ok" in idx.index
    assert idx.files_indexed == 1
