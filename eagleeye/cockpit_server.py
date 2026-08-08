"""Live Cockpit HTTP server for launching reviews and repository evaluations."""
from __future__ import annotations

import json
import mimetypes
import queue
import re
import threading
import time
import uuid
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .core.paths import eagleeye_home, evaluations_root, reviews_root

_event_queue: queue.Queue[str] = queue.Queue()
_event_subscribers: set[queue.Queue[str]] = set()
_state_lock = threading.Lock()
_review_active = False
_current_run: dict[str, Any] | None = None
_runs: deque[dict[str, Any]] = deque(maxlen=100)


def emit_event(event: dict[str, Any]) -> None:
    """Publish a JSON event for Cockpit clients.

    This is intentionally safe to call when no server or event subscriber exists.
    """
    item = json.dumps(event)
    _event_queue.put(item)
    with _state_lock:
        subscribers = list(_event_subscribers)
    for subscriber in subscribers:
        subscriber.put(item)


def _public_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(run) if run is not None else None


def get_status() -> dict[str, Any]:
    """Return the current run and recent run history."""
    with _state_lock:
        return {
            "active": _review_active,
            "current": _public_run(_current_run),
            "runs": [_public_run(run) for run in reversed(_runs)],
        }


def _transition(status: str, **updates: Any) -> dict[str, Any] | None:
    global _current_run
    with _state_lock:
        if _current_run is None:
            return None
        _current_run.update(updates)
        _current_run["status"] = status
        _current_run["updated_at"] = time.time()
        snapshot = dict(_current_run)
    emit_event({"type": "run_status", "status": status, "run": snapshot})
    return snapshot


def _artifact_for_review(
    owner: str,
    repo: str,
    pr_number: int,
    started_at: float,
) -> dict[str, str]:
    repo_dir = reviews_root() / f"{owner}-{repo}"
    candidates = sorted(
        (
            path
            for path in repo_dir.glob(f"pr-{pr_number}-*.md")
            if path.stat().st_mtime >= started_at - 1
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return {}
    md_path = candidates[0]
    html_path = md_path.with_suffix(".html")
    artifact = {
        "markdown": f"/artifacts/reviews/{owner}-{repo}/{md_path.name}",
    }
    if html_path.exists():
        artifact["html"] = f"/artifacts/reviews/{owner}-{repo}/{html_path.name}"
    return artifact


def _artifact_for_evaluation(saved_path: str | Path) -> dict[str, str]:
    path = Path(saved_path).resolve()
    try:
        relative = path.relative_to(evaluations_root().resolve()).as_posix()
    except ValueError:
        return {}
    artifact = {"markdown": f"/artifacts/evaluations/{relative}"}
    html_path = path.with_suffix(".html")
    if html_path.exists():
        html_relative = html_path.relative_to(evaluations_root().resolve()).as_posix()
        artifact["html"] = f"/artifacts/evaluations/{html_relative}"
    return artifact


def _token_metrics(token_usage: Any) -> dict[str, Any]:
    input_tokens = int(getattr(token_usage, "total_input", 0) or 0)
    output_tokens = int(getattr(token_usage, "output_tokens", 0) or 0)
    raw_input = int(getattr(token_usage, "input_tokens", 0) or 0)
    cache_write = int(getattr(token_usage, "cache_creation_input_tokens", 0) or 0)
    cache_read = int(getattr(token_usage, "cache_read_input_tokens", 0) or 0)
    cost = (
        raw_input * 3.0 + cache_write * 3.75 + cache_read * 0.30 + output_tokens * 15.0
    ) / 1_000_000
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
    }


def _append_pilot_record(filename: str, record: dict[str, Any]) -> None:
    """Persist pilot telemetry without allowing telemetry failure to fail a review."""
    try:
        home = eagleeye_home()
        home.mkdir(parents=True, exist_ok=True)
        with (home / filename).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def _pilot_metrics() -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    runs_path = eagleeye_home() / "cockpit-runs.jsonl"
    try:
        for line in runs_path.read_text(encoding="utf-8").splitlines():
            runs.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        runs = list(_runs)
    completed = [run for run in runs if run.get("status") == "completed"]
    failed = [run for run in runs if run.get("status") == "failed"]
    durations = [
        float(run["duration_seconds"])
        for run in completed + failed
        if run.get("duration_seconds") is not None
    ]
    total_cost = sum(
        float(run.get("token_usage", {}).get("cost_usd", 0) or 0)
        for run in completed
    )
    feedback: list[dict[str, Any]] = []
    feedback_path = eagleeye_home() / "cockpit-feedback.jsonl"
    try:
        for line in feedback_path.read_text(encoding="utf-8").splitlines():
            feedback.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    terminal = len(completed) + len(failed)
    return {
        "runs": terminal,
        "completed": len(completed),
        "failed": len(failed),
        "failure_rate": round(len(failed) / terminal, 4) if terminal else 0.0,
        "average_latency_seconds": (
            round(sum(durations) / len(durations), 3) if durations else 0.0
        ),
        "total_cost_usd": round(total_cost, 6),
        "feedback_responses": len(feedback),
        "false_positives_reported": sum(
            max(0, int(item.get("false_positives", 0) or 0)) for item in feedback
        ),
    }


def _run_review_in_thread(owner: str, repo: str, pr_number: int) -> None:
    """Run one review through the same feature boundary used by the CLI."""
    global _review_active
    started = time.time()
    _transition("running", started_at=started)
    try:
        from .core.config import load_config
        from .features.pr_review import run_pr_review

        config = load_config()
        result, _diff, token_usage, _schema_impact, metadata = run_pr_review(
            owner,
            repo,
            pr_number,
            False,
            config,
        )
        finished = time.time()
        completed_run = _transition(
            "completed",
            completed_at=finished,
            duration_seconds=round(finished - started, 3),
            verdict=result.overall_verdict,
            risk_level=result.risk_level,
            artifacts=_artifact_for_review(owner, repo, pr_number, started),
            token_usage=_token_metrics(token_usage),
            title=metadata.get("title", ""),
        )
        if completed_run:
            _append_pilot_record("cockpit-runs.jsonl", completed_run)
    except Exception as exc:
        finished = time.time()
        failed_run = _transition(
            "failed",
            completed_at=finished,
            duration_seconds=round(finished - started, 3),
            error=str(exc),
        )
        if failed_run:
            _append_pilot_record("cockpit-runs.jsonl", failed_run)
    finally:
        with _state_lock:
            _review_active = False


def _run_evaluation_in_thread(
    owner: str,
    repo: str,
    branch: str | None,
    scoped_path: str | None,
    no_llm: bool,
    quick: bool,
    include_data_dirs: bool,
) -> None:
    """Run one repository evaluation through the CLI's feature boundary."""
    global _review_active
    started = time.time()
    _transition("running", started_at=started)
    try:
        from .core.config import load_config
        from .features.repo_evaluate import run_repo_evaluate

        config = load_config(require_claude=not no_llm)
        result, token_usage, saved_path = run_repo_evaluate(
            owner,
            repo,
            config,
            branch=branch,
            scoped_path=scoped_path,
            no_llm=no_llm,
            quick=quick,
            include_data_dirs=include_data_dirs,
        )
        finished = time.time()
        completed_run = _transition(
            "completed",
            completed_at=finished,
            duration_seconds=round(finished - started, 3),
            risk_level=result.risk_level,
            grade=result.ratings.overall_grade,
            artifacts=_artifact_for_evaluation(saved_path),
            token_usage=_token_metrics(token_usage),
            title=f"Evaluation: {owner}/{repo}",
        )
        if completed_run:
            _append_pilot_record("cockpit-runs.jsonl", completed_run)
    except Exception as exc:
        finished = time.time()
        failed_run = _transition(
            "failed",
            completed_at=finished,
            duration_seconds=round(finished - started, 3),
            error=str(exc),
        )
        if failed_run:
            _append_pilot_record("cockpit-runs.jsonl", failed_run)
    finally:
        with _state_lock:
            _review_active = False


def _start_review(owner: str, repo: str, pr_number: int) -> tuple[bool, dict[str, Any]]:
    global _current_run, _review_active
    now = time.time()
    with _state_lock:
        if _review_active:
            return False, dict(_current_run or {})
        run = {
            "id": uuid.uuid4().hex,
            "kind": "review",
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
        }
        _review_active = True
        _current_run = run
        _runs.append(run)
    emit_event({"type": "run_status", "status": "queued", "run": dict(run)})
    thread = threading.Thread(
        target=_run_review_in_thread,
        args=(owner, repo, pr_number),
        daemon=True,
        name=f"eagleeye-review-{run['id'][:8]}",
    )
    thread.start()
    return True, dict(run)


def _start_evaluation(
    owner: str,
    repo: str,
    *,
    branch: str | None = None,
    scoped_path: str | None = None,
    no_llm: bool = False,
    quick: bool = False,
    include_data_dirs: bool = False,
) -> tuple[bool, dict[str, Any]]:
    global _current_run, _review_active
    now = time.time()
    with _state_lock:
        if _review_active:
            return False, dict(_current_run or {})
        run = {
            "id": uuid.uuid4().hex,
            "kind": "evaluation",
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "scoped_path": scoped_path,
            "no_llm": no_llm,
            "quick": quick,
            "include_data_dirs": include_data_dirs,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
        }
        _review_active = True
        _current_run = run
        _runs.append(run)
    emit_event({"type": "run_status", "status": "queued", "run": dict(run)})
    thread = threading.Thread(
        target=_run_evaluation_in_thread,
        args=(owner, repo, branch, scoped_path, no_llm, quick, include_data_dirs),
        daemon=True,
        name=f"eagleeye-evaluate-{run['id'][:8]}",
    )
    thread.start()
    return True, dict(run)


def _review_records() -> list[dict[str, Any]]:
    from .presentation.html.dashboard import (
        _group_evaluations,
        _group_reviews,
        _scan_evaluations,
        _scan_reviews,
    )

    records: list[dict[str, Any]] = []
    for row in _group_reviews(_scan_reviews()):
        item = dict(row)
        item["type"] = "review"
        item["artifacts"] = {
            key: f"/artifacts/reviews/{value}"
            for key, value in (("html", row.get("html")), ("markdown", row.get("md")))
            if value
        }
        records.append(item)
    for row in _group_evaluations(_scan_evaluations()):
        item = dict(row)
        item["type"] = "evaluation"
        artifacts = {}
        for key, value in (("html", row.get("html")), ("markdown", row.get("md"))):
            if not value:
                continue
            normalized = str(value).replace("\\", "/")
            marker = "evaluations/"
            relative = normalized.split(marker, 1)[1] if marker in normalized else normalized
            artifacts[key] = f"/artifacts/evaluations/{relative.lstrip('/')}"
        item["artifacts"] = artifacts
        records.append(item)
    records.sort(key=lambda row: row.get("timestamp", 0), reverse=True)
    return records


def _safe_artifact(path: str) -> Path | None:
    prefixes = {
        "/artifacts/reviews/": reviews_root(),
        "/artifacts/evaluations/": evaluations_root(),
    }
    for prefix, root in prefixes.items():
        if path.startswith(prefix):
            relative = unquote(path[len(prefix) :])
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                return None
            return candidate
    return None


class CockpitHandler(BaseHTTPRequestHandler):
    server_version = "EagleEyeCockpit/2"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            from .presentation.html.dashboard import build_dashboard

            self._file(build_dashboard())
            return
        if path == "/status":
            self._json(HTTPStatus.OK, get_status())
            return
        if path == "/reviews":
            self._json(HTTPStatus.OK, _review_records())
            return
        if path == "/metrics":
            self._json(HTTPStatus.OK, _pilot_metrics())
            return
        if path == "/events":
            subscriber: queue.Queue[str] = queue.Queue()
            with _state_lock:
                _event_subscribers.add(subscriber)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    try:
                        event = subscriber.get(timeout=15)
                        self.wfile.write(f"data: {event}\n\n".encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with _state_lock:
                    _event_subscribers.discard(subscriber)
            return
        artifact = _safe_artifact(path)
        if artifact is not None:
            self._file(artifact)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/run", "/evaluate", "/feedback"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 16_384:
                raise ValueError
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON request"})
            return

        if path == "/feedback":
            try:
                run_id = str(payload["run_id"]).strip()
                false_positives = int(payload.get("false_positives", 0))
                notes = str(payload.get("notes", "")).strip()[:2000]
                if not run_id or false_positives < 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "run_id and a non-negative false_positives value are required"},
                )
                return
            record = {
                "run_id": run_id,
                "false_positives": false_positives,
                "notes": notes,
                "created_at": time.time(),
            }
            _append_pilot_record("cockpit-feedback.jsonl", record)
            self._json(HTTPStatus.OK, {"status": "recorded"})
            return

        valid_slug = re.compile(r"^[A-Za-z0-9_.-]+$")
        if path == "/evaluate":
            try:
                owner = str(payload["owner"]).strip()
                repo = str(payload["repo"]).strip()
                branch = str(payload.get("branch") or "").strip() or None
                scoped_path = str(payload.get("path") or "").strip() or None
                mode_values = {
                    "no_llm": payload.get("no_llm", False),
                    "quick": payload.get("quick", False),
                    "include_data_dirs": payload.get("include_data_dirs", False),
                }
                if not all(isinstance(value, bool) for value in mode_values.values()):
                    raise ValueError
                no_llm = mode_values["no_llm"]
                quick = mode_values["quick"]
                include_data_dirs = mode_values["include_data_dirs"]
                if not valid_slug.fullmatch(owner) or not valid_slug.fullmatch(repo):
                    raise ValueError
                if scoped_path and (
                    ".." in Path(scoped_path).parts or Path(scoped_path).is_absolute()
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "valid owner, repo, branch, and relative path are required"},
                )
                return
            started, run = _start_evaluation(
                owner,
                repo,
                branch=branch,
                scoped_path=scoped_path,
                no_llm=no_llm,
                quick=quick,
                include_data_dirs=include_data_dirs,
            )
            if not started:
                self._json(
                    HTTPStatus.CONFLICT,
                    {"error": "a Cockpit job is already active", "run": run},
                )
                return
            self._json(HTTPStatus.OK, {"status": "started", "run": run})
            return

        try:
            owner = str(payload["owner"]).strip()
            repo = str(payload["repo"]).strip()
            pr_number = int(payload["pr_number"])
            if (
                not valid_slug.fullmatch(owner)
                or not valid_slug.fullmatch(repo)
                or pr_number < 1
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"error": "owner, repo, and a positive pr_number are required"},
            )
            return

        started, run = _start_review(owner, repo, pr_number)
        if not started:
            self._json(
                HTTPStatus.CONFLICT,
                {"error": "a Cockpit job is already active", "run": run},
            )
            return
        self._json(HTTPStatus.OK, {"status": "started", "run": run})


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve Cockpit until interrupted."""
    server = ThreadingHTTPServer((host, port), CockpitHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
