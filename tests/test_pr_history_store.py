import pytest
from eagleeye.pr_history_store import (
    PRHistoryEntry,
    add_entry,
    get_relevant,
    load_history,
    format_history_prompt,
)


@pytest.fixture
def tmp_history_dir(tmp_path, monkeypatch):
    hist_dir = tmp_path / "history"
    hist_dir.mkdir()
    import eagleeye.pr_history_store as m
    monkeypatch.setattr(m, "_HISTORY_DIR", hist_dir)
    return hist_dir


def _entry(pr_number: int, files: list[str], verdict="request_changes", risk="high") -> PRHistoryEntry:
    return PRHistoryEntry(
        pr_number=pr_number,
        title=f"PR {pr_number} title",
        merged_at="2026-03-15T10:00:00Z",
        author="alice",
        files_changed=files,
        body_snippet="Some description",
        verdict=verdict,
        risk_level=risk,
        summary=f"Summary of PR {pr_number}",
    )


def test_add_and_load_entry(tmp_history_dir):
    add_entry("org", "repo", _entry(42, ["src/foo.py"]))
    history = load_history("org", "repo")
    assert len(history) == 1
    assert history[0].pr_number == 42


def test_add_entry_no_duplicate(tmp_history_dir):
    add_entry("org", "repo", _entry(42, ["src/foo.py"]))
    updated = _entry(42, ["src/foo.py", "src/bar.py"])
    updated.summary = "Updated summary"
    add_entry("org", "repo", updated)
    history = load_history("org", "repo")
    assert len(history) == 1
    assert history[0].summary == "Updated summary"


def test_get_relevant_file_overlap(tmp_history_dir):
    add_entry("org", "repo", _entry(10, ["src/models/account.py", "src/utils.py"]))
    add_entry("org", "repo", _entry(11, ["src/jobs/etl.py"]))
    add_entry("org", "repo", _entry(12, ["src/models/account.py"]))
    matches = get_relevant("org", "repo", ["src/models/account.py", "src/new_feature.py"])
    numbers = [e.pr_number for e in matches]
    assert 10 in numbers
    assert 12 in numbers
    assert 11 not in numbers


def test_get_relevant_capped_at_5(tmp_history_dir):
    for i in range(10):
        add_entry("org", "repo", _entry(i, ["shared.py"]))
    matches = get_relevant("org", "repo", ["shared.py"])
    assert len(matches) <= 5


def test_get_relevant_sorted_by_recency(tmp_history_dir):
    e_old = _entry(1, ["a.py"])
    e_old.merged_at = "2025-01-01T00:00:00Z"
    e_new = _entry(2, ["a.py"])
    e_new.merged_at = "2026-04-01T00:00:00Z"
    add_entry("org", "repo", e_old)
    add_entry("org", "repo", e_new)
    matches = get_relevant("org", "repo", ["a.py"])
    assert matches[0].pr_number == 2


def test_format_history_prompt(tmp_history_dir):
    entries = [_entry(58, ["src/models/account.py"])]
    prompt = format_history_prompt(entries)
    assert "PR #58" in prompt
    assert "HIGH" in prompt
    assert "PR History" in prompt


def test_format_history_prompt_empty(tmp_history_dir):
    assert format_history_prompt([]) == ""
