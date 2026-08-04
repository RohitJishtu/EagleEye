"""Tests for evaluate module partitioning."""

from __future__ import annotations

from eagleeye.workflows.repo_evaluate.modules import (
    MAX_FILES_PER_MODULE,
    partition_modules,
    select_module_files,
)


def _tree(paths: list[str]) -> list[dict]:
    return [{"path": p, "type": "blob"} for p in paths]


def test_partition_prefers_core_excludes_data_and_tests():
    tree = _tree([
        "core/ingest.py",
        "core/models.py",
        "core/agent.py",
        "ui/app.py",
        "ui/pages.py",
        "data/issues.json",
        "data/more.json",
        "tests/test_ingest.py",
        "tests/test_ui.py",
        "main.py",
        "README.md",
        "config.yml",
    ])
    plans = partition_modules(tree)
    names = [p.name for p in plans]
    assert "core" in names
    assert "data" not in names
    assert "tests" not in names
    assert names[0] == "core"  # preferred + more files


def test_select_module_files_caps_at_12():
    paths = [f"core/mod_{i}.py" for i in range(30)]
    paths = ["core/main.py", "core/__init__.py", "core/config.yml"] + paths
    selected = select_module_files(paths, max_files=MAX_FILES_PER_MODULE)
    assert len(selected) == MAX_FILES_PER_MODULE
    assert "core/main.py" in selected
    assert "core/__init__.py" in selected


def test_partition_respects_scoped_path():
    tree = _tree([
        "pkg/core/a.py",
        "pkg/core/b.py",
        "pkg/ui/c.py",
        "pkg/ui/d.py",
        "other/x.py",
        "other/y.py",
    ])
    plans = partition_modules(tree, scoped_path="pkg")
    names = {p.name for p in plans}
    assert "core" in names or "ui" in names
    assert "other" not in names
    for plan in plans:
        assert all(p.startswith("pkg/") for p in plan.paths)


def test_partition_max_modules():
    tree = _tree([
        f"mod{i}/a.py" for i in range(10)
    ] + [
        f"mod{i}/b.py" for i in range(10)
    ])
    # Give preferred name boost to one
    tree += [{"path": "core/x.py", "type": "blob"}, {"path": "core/y.py", "type": "blob"}]
    plans = partition_modules(tree, max_modules=6)
    assert len(plans) <= 6
    assert plans[0].name == "core"
