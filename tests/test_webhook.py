"""Tests for the EagleEye webhook server."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from eagleeye.webhook.server import _verify_signature, app


@pytest.fixture(autouse=True)
def _dev_webhooks(monkeypatch):
    monkeypatch.setenv("EAGLEEYE_DEV", "1")


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_verify_signature_valid():
    secret = "mysecret"
    payload = b'{"action": "opened"}'
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    import eagleeye.webhook.server as ws
    ws._webhook_secret = secret
    assert _verify_signature(payload, sig) is True


def test_verify_signature_invalid():
    import eagleeye.webhook.server as ws
    ws._webhook_secret = "mysecret"
    assert _verify_signature(b"payload", "sha256=wrongsig") is False


def test_verify_signature_no_secret_allows_all():
    import eagleeye.webhook.server as ws
    ws._webhook_secret = ""
    assert _verify_signature(b"anything", "") is True
    assert _verify_signature(b"anything", "sha256=bogus") is True


def test_verify_signature_no_secret_rejected_outside_dev(monkeypatch):
    import eagleeye.webhook.server as ws

    monkeypatch.delenv("EAGLEEYE_DEV", raising=False)
    ws._webhook_secret = ""
    assert _verify_signature(b"anything", "") is False


def test_require_webhook_secret_outside_dev(monkeypatch):
    import eagleeye.webhook.server as ws

    monkeypatch.delenv("EAGLEEYE_DEV", raising=False)
    ws._webhook_secret = ""
    with pytest.raises(RuntimeError, match="GITHUB_WEBHOOK_SECRET"):
        ws._require_webhook_secret()


# ---------------------------------------------------------------------------
# Webhook event handling
# ---------------------------------------------------------------------------


def _make_pr_payload(action: str = "opened", pr_number: int = 42) -> dict:
    return {
        "action": action,
        "pull_request": {"number": pr_number, "title": f"PR #{pr_number}"},
        "repository": {"full_name": "owner/testrepo"},
    }


def test_pr_opened_queues_review(client):
    import eagleeye.webhook.server as ws
    ws._webhook_secret = ""

    with patch("eagleeye.webhook.server._run_review_sync"):
        resp = client.post(
            "/webhook/github",
            json=_make_pr_payload("opened", 1),
            headers={"X-GitHub-Event": "pull_request"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["pr"] == 1
    assert data["repo"] == "owner/testrepo"


def test_pr_synchronize_queues_review(client):
    import eagleeye.webhook.server as ws
    ws._webhook_secret = ""

    with patch("eagleeye.webhook.server._run_review_sync"):
        resp = client.post(
            "/webhook/github",
            json=_make_pr_payload("synchronize", 7),
            headers={"X-GitHub-Event": "pull_request"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_pr_reopened_queues_review(client):
    import eagleeye.webhook.server as ws
    ws._webhook_secret = ""

    with patch("eagleeye.webhook.server._run_review_sync"):
        resp = client.post(
            "/webhook/github",
            json=_make_pr_payload("reopened", 3),
            headers={"X-GitHub-Event": "pull_request"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_unsupported_action_ignored(client):
    import eagleeye.webhook.server as ws
    ws._webhook_secret = ""

    resp = client.post(
        "/webhook/github",
        json=_make_pr_payload("labeled"),
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_non_pr_event_ignored(client):
    import eagleeye.webhook.server as ws
    ws._webhook_secret = ""

    resp = client.post(
        "/webhook/github",
        json={"action": "pushed"},
        headers={"X-GitHub-Event": "push"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_invalid_signature_returns_401(client):
    import eagleeye.webhook.server as ws
    ws._webhook_secret = "supersecret"

    resp = client.post(
        "/webhook/github",
        json=_make_pr_payload("opened"),
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=wrongsignature",
        },
    )
    assert resp.status_code == 401


def test_valid_hmac_signature_accepted(client):
    import eagleeye.webhook.server as ws

    secret = "topsecret"
    ws._webhook_secret = secret
    payload = json.dumps(_make_pr_payload("opened", 99)).encode()
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    with patch("eagleeye.webhook.server._run_review_sync"):
        resp = client.post(
            "/webhook/github",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
