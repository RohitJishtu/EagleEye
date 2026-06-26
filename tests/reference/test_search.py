from eagleeye.reference_store import Match, ReferenceIndex, search_indexes


def _make_idx(owner, repo, entries):
    idx = ReferenceIndex(
        owner=owner, repo=repo, ref="main",
        built_at="2026-05-18T00:00:00Z", files_indexed=1,
    )
    for name, matches in entries.items():
        idx.index[name] = matches
    return idx


def test_search_returns_empty_when_nothing_matches():
    idx = _make_idx("org", "a", {"foo": [Match("a.py", 1, "py.def", "def foo():")]})
    md = search_indexes([idx], {"bar"})
    assert md == ""


def test_search_returns_markdown_with_matches():
    idx = _make_idx("org", "a", {
        "load_pipeline": [Match("etl/runner.py", 18, "py.call", "result = load_pipeline(cfg)")],
    })
    md = search_indexes([idx], {"load_pipeline"})
    assert "org/a" in md
    assert "load_pipeline" in md
    assert "etl/runner.py:18" in md
    assert "py.call" in md


def test_search_omits_repos_with_zero_hits():
    a = _make_idx("org", "a", {"foo": [Match("a.py", 1, "py.def", "x")]})
    b = _make_idx("org", "b", {"bar": [Match("b.py", 1, "py.def", "x")]})
    md = search_indexes([a, b], {"foo"})
    assert "org/a" in md
    assert "org/b" not in md


def test_search_caps_matches_per_name_in_markdown():
    matches = [Match(f"f{i}.py", i + 1, "py.call", f"x{i}") for i in range(25)]
    idx = _make_idx("org", "a", {"foo": matches})
    md = search_indexes([idx], {"foo"})
    assert md.count("f0.py:1") == 1
    assert md.count("f9.py:10") == 1
    assert "f24.py" not in md
    assert "and 15 more" in md


def test_search_summary_line_present():
    a = _make_idx("org", "a", {"foo": [Match("a.py", 1, "py.def", "x")]})
    b = _make_idx("org", "b", {"foo": [Match("b.py", 1, "py.def", "x")]})
    md = search_indexes([a, b], {"foo"})
    assert "Reference scan:" in md
    assert "across 2 repo" in md
