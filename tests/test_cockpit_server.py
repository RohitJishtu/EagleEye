"""Tests for cockpit_server — event queue, /run, /reviews endpoints."""

import pytest

pytestmark = pytest.mark.skip(reason="Cockpit v2 server not implemented; static cockpit only")

import json
import time
import http.client
import threading


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


def test_reviews_endpoint_returns_json(monkeypatch):
    monkeypatch.setattr("eagleeye.presentation.html.dashboard._scan_reviews", lambda: [])
    monkeypatch.setattr("eagleeye.presentation.html.dashboard._group_reviews", lambda rows: [])
    _start_server(17893)
    conn = http.client.HTTPConnection("localhost", 17893, timeout=3)
    conn.request("GET", "/reviews")
    resp = conn.getresponse()
    assert resp.status == 200
    assert isinstance(json.loads(resp.read()), list)
    conn.close()
