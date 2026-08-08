"""Tests for cockpit_server — event queue, /run, /reviews endpoints."""

import http.client
import json
import queue
import threading
import time
from types import SimpleNamespace


def test_emit_event_puts_json_on_queue():
    import eagleeye.cockpit_server as cs
    while not cs._event_queue.empty():
        cs._event_queue.get_nowait()
    cs.emit_event({"type": "agent_done", "agent": "pr"})
    item = cs._event_queue.get_nowait()
    assert json.loads(item) == {"type": "agent_done", "agent": "pr"}


def test_emit_event_callable_without_server():
    from eagleeye.cockpit_server import emit_event
    emit_event({"type": "test"})  # must not raise


def test_emit_event_broadcasts_to_all_subscribers():
    import eagleeye.cockpit_server as cs

    first: queue.Queue[str] = queue.Queue()
    second: queue.Queue[str] = queue.Queue()
    with cs._state_lock:
        cs._event_subscribers.update((first, second))
    try:
        cs.emit_event({"type": "status"})
        assert json.loads(first.get_nowait()) == {"type": "status"}
        assert json.loads(second.get_nowait()) == {"type": "status"}
    finally:
        with cs._state_lock:
            cs._event_subscribers.difference_update((first, second))


def _start_server(port: int) -> None:
    import eagleeye.cockpit_server as cs
    t = threading.Thread(target=lambda: cs.serve(port=port), daemon=True)
    t.start()
    time.sleep(0.2)


def test_run_returns_409_when_active(monkeypatch):
    import eagleeye.cockpit_server as cs
    monkeypatch.setattr(cs, "_review_active", True)
    _start_server(17891)
    conn = http.client.HTTPConnection("localhost", 17891, timeout=3)
    body = json.dumps({"owner": "o", "repo": "r", "pr_number": 1}).encode()
    conn.request("POST", "/run", body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 409
    conn.close()
    monkeypatch.setattr(cs, "_review_active", False)


def test_run_returns_200_when_idle(monkeypatch):
    import eagleeye.cockpit_server as cs
    monkeypatch.setattr(cs, "_review_active", False)
    monkeypatch.setattr(cs, "_run_review_in_thread", lambda o, r, n: None)
    _start_server(17892)
    conn = http.client.HTTPConnection("localhost", 17892, timeout=3)
    body = json.dumps({"owner": "o", "repo": "r", "pr_number": 1}).encode()
    conn.request("POST", "/run", body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 200
    assert json.loads(resp.read())["status"] == "started"
    conn.close()


def test_evaluate_returns_200_with_mode_options(monkeypatch):
    import eagleeye.cockpit_server as cs

    monkeypatch.setattr(cs, "_review_active", False)
    monkeypatch.setattr(cs, "_run_evaluation_in_thread", lambda *args: None)
    _start_server(17895)
    conn = http.client.HTTPConnection("localhost", 17895, timeout=3)
    body = json.dumps(
        {
            "owner": "acme",
            "repo": "demo",
            "branch": "develop",
            "path": "src/core",
            "quick": True,
            "no_llm": True,
            "include_data_dirs": False,
        }
    ).encode()
    conn.request("POST", "/evaluate", body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 200
    run = json.loads(resp.read())["run"]
    assert run["kind"] == "evaluation"
    assert run["branch"] == "develop"
    assert run["scoped_path"] == "src/core"
    assert run["quick"] is True
    assert run["no_llm"] is True
    conn.close()
    monkeypatch.setattr(cs, "_review_active", False)


def test_reviews_endpoint_returns_json(monkeypatch):
    monkeypatch.setattr("eagleeye.presentation.html.dashboard._scan_reviews", lambda: [])
    monkeypatch.setattr("eagleeye.presentation.html.dashboard._group_reviews", lambda rows: [])
    monkeypatch.setattr("eagleeye.presentation.html.dashboard._scan_evaluations", lambda: [])
    monkeypatch.setattr("eagleeye.presentation.html.dashboard._group_evaluations", lambda rows: [])
    _start_server(17893)
    conn = http.client.HTTPConnection("localhost", 17893, timeout=3)
    conn.request("GET", "/reviews")
    resp = conn.getresponse()
    assert resp.status == 200
    assert isinstance(json.loads(resp.read()), list)
    conn.close()


def test_feedback_endpoint_records_false_positives(monkeypatch, tmp_path):
    import eagleeye.cockpit_server as cs

    monkeypatch.setattr(cs, "eagleeye_home", lambda: tmp_path)
    _start_server(17894)
    conn = http.client.HTTPConnection("localhost", 17894, timeout=3)
    body = json.dumps(
        {"run_id": "pilot-run", "false_positives": 2, "notes": "Two noisy findings"}
    ).encode()
    conn.request("POST", "/feedback", body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 200
    assert json.loads(resp.read())["status"] == "recorded"
    conn.close()
    assert cs._pilot_metrics()["false_positives_reported"] == 2


def test_artifact_lookup_does_not_reuse_an_old_report(monkeypatch, tmp_path):
    import eagleeye.cockpit_server as cs

    monkeypatch.setattr(cs, "reviews_root", lambda: tmp_path)
    repo_dir = tmp_path / "acme-demo"
    repo_dir.mkdir()
    report = repo_dir / "pr-7-old-100.md"
    report.write_text("old")

    assert cs._artifact_for_review("acme", "demo", 7, time.time() + 10) == {}
    assert cs._artifact_for_review("acme", "demo", 7, time.time() - 1)["markdown"].endswith(
        report.name
    )


def test_review_lifecycle_completes_through_feature_boundary(monkeypatch, tmp_path):
    import eagleeye.cockpit_server as cs
    import eagleeye.core.config as config_module
    import eagleeye.features.pr_review as feature_module

    monkeypatch.setattr(cs, "eagleeye_home", lambda: tmp_path)
    result = SimpleNamespace(overall_verdict="approve", risk_level="low")
    usage = SimpleNamespace(
        total_input=100,
        output_tokens=20,
        input_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    monkeypatch.setattr(config_module, "load_config", lambda: object())
    monkeypatch.setattr(
        feature_module,
        "run_pr_review",
        lambda owner, repo, pr, post, config: (
            result,
            "",
            usage,
            None,
            {"title": "Pilot PR"},
        ),
    )
    cs._current_run = {
        "id": "pilot",
        "owner": "acme",
        "repo": "demo",
        "pr_number": 7,
        "status": "queued",
    }
    cs._review_active = True

    cs._run_review_in_thread("acme", "demo", 7)

    status = cs.get_status()
    assert status["active"] is False
    assert status["current"]["status"] == "completed"
    assert status["current"]["title"] == "Pilot PR"
    assert status["current"]["token_usage"]["cost_usd"] > 0
    metrics = cs._pilot_metrics()
    assert metrics["completed"] == 1
    assert metrics["failed"] == 0
    assert metrics["average_latency_seconds"] >= 0


def test_review_lifecycle_records_failure(monkeypatch, tmp_path):
    import eagleeye.cockpit_server as cs
    import eagleeye.core.config as config_module

    monkeypatch.setattr(cs, "eagleeye_home", lambda: tmp_path)
    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: (_ for _ in ()).throw(RuntimeError("bad auth")),
    )
    cs._current_run = {
        "id": "failed-pilot",
        "owner": "acme",
        "repo": "demo",
        "pr_number": 8,
        "status": "queued",
    }
    cs._review_active = True

    cs._run_review_in_thread("acme", "demo", 8)

    status = cs.get_status()
    assert status["active"] is False
    assert status["current"]["status"] == "failed"
    assert status["current"]["error"] == "bad auth"
    assert cs._pilot_metrics()["failure_rate"] == 1.0


def test_evaluation_lifecycle_completes_through_feature_boundary(monkeypatch, tmp_path):
    import eagleeye.cockpit_server as cs
    import eagleeye.core.config as config_module
    import eagleeye.features.repo_evaluate as feature_module

    evaluation_root = tmp_path / "evaluations"
    saved_path = evaluation_root / "acme-demo" / "eval-demo-1.md"
    saved_path.parent.mkdir(parents=True)
    saved_path.write_text("evaluation")
    saved_path.with_suffix(".html").write_text("<html></html>")
    monkeypatch.setattr(cs, "eagleeye_home", lambda: tmp_path)
    monkeypatch.setattr(cs, "evaluations_root", lambda: evaluation_root)
    monkeypatch.setattr(config_module, "load_config", lambda require_claude=True: object())
    captured = {}

    def fake_evaluate(owner, repo, config, **kwargs):
        captured.update(kwargs)
        result = SimpleNamespace(
            risk_level="medium",
            ratings=SimpleNamespace(overall_grade="B"),
        )
        usage = SimpleNamespace(
            total_input=0,
            output_tokens=0,
            input_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        return result, usage, str(saved_path)

    monkeypatch.setattr(feature_module, "run_repo_evaluate", fake_evaluate)
    cs._current_run = {
        "id": "evaluate-pilot",
        "kind": "evaluation",
        "owner": "acme",
        "repo": "demo",
        "status": "queued",
    }
    cs._review_active = True

    cs._run_evaluation_in_thread(
        "acme",
        "demo",
        "develop",
        "src",
        True,
        True,
        False,
    )

    current = cs.get_status()["current"]
    assert current["status"] == "completed"
    assert current["grade"] == "B"
    assert current["artifacts"]["html"].endswith("eval-demo-1.html")
    assert captured == {
        "branch": "develop",
        "scoped_path": "src",
        "no_llm": True,
        "quick": True,
        "include_data_dirs": False,
    }
