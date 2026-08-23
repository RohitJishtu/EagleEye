"""Tests for Cockpit dashboard — PR reviews and repo evaluations."""

from __future__ import annotations

from pathlib import Path

import pytest

from eagleeye.presentation.html import dashboard as dash


@pytest.fixture
def cockpit_dirs(tmp_path, monkeypatch):
    reviews = tmp_path / "reviews"
    evaluations = tmp_path / "evaluations"
    reviews.mkdir()
    evaluations.mkdir()
    monkeypatch.setattr(dash, "reviews_root", lambda: reviews)
    monkeypatch.setattr(dash, "evaluations_root", lambda: evaluations)
    monkeypatch.setattr(dash, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(dash, "EVALUATIONS_DIR", evaluations)
    return reviews, evaluations


def _write_eval(evaluations: Path, repo: str, risk: str = "HIGH", summary: str = "Test repo summary.") -> Path:
    owner, name = repo.split("/", 1)
    out_dir = evaluations / f"{owner}-{name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "eval-test-1700000000.md"
    md.write_text(
        f"---\n"
        f"repo: {repo}\n"
        f"branch: main\n"
        f"date: 2026-07-10 12:00 UTC\n"
        f"timestamp_utc: 1700000000\n"
        f"risk_level: {risk.lower()}\n"
        f"synthesis_failed: False\n"
        f"---\n\n"
        f"# Repo Evaluation: {repo}\n\n"
        f"## Executive summary\n\n{summary}\n"
    )
    return md


def test_scan_evaluations_picks_up_eval_md(cockpit_dirs):
    _, evaluations = cockpit_dirs
    _write_eval(evaluations, "acme/widget", risk="CRITICAL")

    rows = dash._scan_evaluations()
    assert len(rows) == 1
    assert rows[0]["repo"] == "acme/widget"
    assert rows[0]["risk"] == "CRITICAL"
    assert "Test repo summary" in rows[0]["summary"]


def test_group_evaluations_keeps_latest_per_repo(cockpit_dirs):
    _, evaluations = cockpit_dirs
    owner_dir = evaluations / "acme-widget"
    owner_dir.mkdir(parents=True, exist_ok=True)
    for ts, summary in [(1700000000, "older"), (1700000100, "newer")]:
        (owner_dir / f"eval-widget-{ts}.md").write_text(
            f"---\nrepo: acme/widget\nbranch: main\ndate: 2026-07-10\ntimestamp_utc: {ts}\n"
            f"risk_level: high\nsynthesis_failed: False\n---\n\n"
            f"## Executive summary\n\n{summary}\n"
        )

    grouped = dash._group_evaluations(dash._scan_evaluations())
    assert len(grouped) == 1
    assert grouped[0]["summary"] == "newer"
    assert len(grouped[0]["history"]) == 2


def test_build_dashboard_includes_evaluations_tab(cockpit_dirs):
    reviews, evaluations = cockpit_dirs
    md = _write_eval(evaluations, "acme/widget")

    out = dash.build_dashboard()
    html = out.read_text(encoding="utf-8")

    assert out == reviews / "index.html"
    assert "Repo Evaluations" in html
    assert "eval-card" in html
    assert "acme/widget" in html
    assert "Latest" in html
    assert "../evaluations/acme-widget/eval-test-1700000000.html#action-summary" in html
    assert 'id="run-form"' in html
    assert 'id="evaluate-form"' in html
    assert 'id="refresh-button"' in html
    assert "function refreshForms()" in html
    assert "fetch(apiUrl('/evaluate')" in html
    assert "EventSource(apiUrl('/events'))" in html


def test_build_dashboard_live_uses_artifact_urls(cockpit_dirs):
    reviews, evaluations = cockpit_dirs
    md = _write_eval(evaluations, "acme/widget")
    md.with_suffix(".html").write_text("<html></html>")
    repo_dir = reviews / "acme-widget"
    repo_dir.mkdir()
    (repo_dir / "pr-9-demo.md").write_text(
        "---\nrepo: acme/widget\npr: 9\ntitle: <script>alert(1)</script>\n"
        "date: 2026-07-10\ntimestamp_utc: 1700000000\nurl: javascript:alert(1)\n---\n"
        "## EagleEye Code Review ✅\n"
    )
    (repo_dir / "pr-9-demo.html").write_text("<html></html>")

    html = dash.build_dashboard(live=True).read_text(encoding="utf-8")
    assert "/artifacts/evaluations/acme-widget/eval-test-1700000000.html#action-summary" in html
    assert "/artifacts/reviews/acme-widget/pr-9-demo.html" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'href="javascript:alert(1)"' not in html
    assert "onclick=\"rerunReview(" not in html
    assert 'class="open-btn rerun-review"' in html
    assert 'class="card-actions"' in html
    assert ".card-actions" in html
