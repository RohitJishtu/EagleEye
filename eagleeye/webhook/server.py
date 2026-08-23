"""FastAPI webhook server for GitHub pull_request events.

Receives GitHub webhooks and triggers multi-agent PR reviews automatically.

Setup:
  1. Start:  eagleeye serve --port 8080
  2. In GitHub repo settings → Webhooks → Add webhook:
       Payload URL: http://your-host:8080/webhook/github
       Content type: application/json
       Secret: (set GITHUB_WEBHOOK_SECRET env var to the same value)
       Events: Pull requests

Set GITHUB_WEBHOOK_SECRET to validate HMAC-SHA256 signatures.
Outside development the secret is required; set EAGLEEYE_DEV=1 to allow
unsigned local testing.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_webhook_secret: str = ""


def _is_dev_mode() -> bool:
    return os.environ.get("EAGLEEYE_DEV", "").strip().lower() in {"1", "true", "yes"}


def _require_webhook_secret() -> None:
    if _webhook_secret or _is_dev_mode():
        return
    raise RuntimeError(
        "GITHUB_WEBHOOK_SECRET is required outside development. "
        "Set the secret or EAGLEEYE_DEV=1 for local unsigned testing."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _webhook_secret
    _webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    _require_webhook_secret()
    if not _webhook_secret:
        logger.warning(
            "GITHUB_WEBHOOK_SECRET is not set — "
            "signature validation is disabled (EAGLEEYE_DEV)"
        )
    yield


app = FastAPI(
    title="EagleEye Webhook",
    description="Receives GitHub pull_request events and triggers automated AI code reviews.",
    lifespan=lifespan,
)


def _verify_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """Validate GitHub HMAC-SHA256 webhook signature (constant-time comparison)."""
    if not _webhook_secret:
        return _is_dev_mode()
    expected = "sha256=" + hmac.new(
        _webhook_secret.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """Handle incoming GitHub webhook events."""
    payload_bytes = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not _verify_signature(payload_bytes, sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    payload = json.loads(payload_bytes)
    action = payload.get("action", "")

    if event_type == "pull_request" and action in ("opened", "synchronize", "reopened"):
        pr = payload["pull_request"]
        repo_full = payload["repository"]["full_name"]
        owner, repo = repo_full.split("/", 1)
        pr_number = pr["number"]
        pr_title = pr.get("title", f"PR #{pr_number}")
        logger.info("Queuing review for %s#%d (%s)", repo_full, pr_number, action)
        background_tasks.add_task(_review_pr_background, owner, repo, pr_number)
        return JSONResponse(
            {"status": "queued", "repo": repo_full, "pr": pr_number, "title": pr_title}
        )

    logger.debug("Ignoring event: %s / %s", event_type, action)
    return JSONResponse({"status": "ignored", "event": event_type, "action": action})


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe."""
    return JSONResponse({"status": "ok", "service": "eagleeye-webhook"})


async def _review_pr_background(owner: str, repo: str, pr_number: int) -> None:
    """Bridge async FastAPI handler to synchronous review pipeline."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_review_sync, owner, repo, pr_number)


def _run_review_sync(owner: str, repo: str, pr_number: int) -> None:
    """Load config and run the multi-agent review, posting the result to GitHub."""
    from ..core.config import load_config
    from ..features.pr_review import run_pr_review

    try:
        config = load_config()
        run_pr_review(owner, repo, pr_number, post_comment=True, config=config)
        logger.info("Review complete for %s/%s#%d", owner, repo, pr_number)
    except Exception as exc:
        logger.error("Review failed for %s/%s#%d: %s", owner, repo, pr_number, exc)


def run_server(host: str = "0.0.0.0", port: int = 8080, reload: bool = False) -> None:
    """Start the uvicorn ASGI server."""
    import uvicorn

    global _webhook_secret
    _webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    _require_webhook_secret()
    uvicorn.run("eagleeye.webhook.server:app", host=host, port=port, reload=reload)
