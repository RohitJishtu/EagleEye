"""Persist PR review results to markdown files."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path

from ...core.models import PRReviewResult
from .formatting import format_comment_markdown

_DEFAULT_REVIEWS_DIR = str(Path(__file__).resolve().parent.parent.parent.parent / "reviews")


def slugify_title(pr_title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", pr_title.lower()).strip("-")[:60]


def _repo_reviews_dir(owner: str, repo: str) -> Path:
    try:
        from ...core.paths import reviews_dir as reviews_dir_for_repo

        return reviews_dir_for_repo(owner, repo)
    except ImportError:
        base = Path(os.environ.get("EAGLEEYE_REVIEWS_DIR", _DEFAULT_REVIEWS_DIR))
        return base / f"{owner}-{repo}"


def save_review(
    owner: str,
    repo: str,
    pr_number: int,
    pr_title: str,
    result: PRReviewResult,
    file_manifest: list | None = None,
    token_usage=None,
    pr_status: str = "",
) -> Path:
    slug = slugify_title(pr_title)
    date_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    ts = int(time.time())
    filename = f"pr-{pr_number}-{slug}-{ts}.md"

    reviews_dir = _repo_reviews_dir(owner, repo)
    reviews_dir.mkdir(parents=True, exist_ok=True)

    files_fm = ""
    if file_manifest:
        fetched = [m["file"] for m in file_manifest if m["status"] in ("ok", "truncated")]
        skipped = [m["file"] for m in file_manifest if m["status"] not in ("ok", "truncated")]
        files_fm = f"files_analyzed: {len(fetched)}\n"
        if fetched:
            files_fm += "files_read:\n" + "".join(f"  - {f}\n" for f in fetched)
        if skipped:
            files_fm += "files_skipped:\n" + "".join(f"  - {f}\n" for f in skipped)

    ts_fm = f"timestamp_utc: {ts}\n"

    token_fm = ""
    if token_usage is not None:
        total_in = getattr(token_usage, "total_input", 0)
        total_out = getattr(token_usage, "output_tokens", 0)
        inp   = getattr(token_usage, "input_tokens", 0)
        cw    = getattr(token_usage, "cache_creation_input_tokens", 0)
        cr    = getattr(token_usage, "cache_read_input_tokens", 0)
        cost  = (inp * 3.0 + cw * 3.75 + cr * 0.30 + total_out * 15.0) / 1_000_000
        token_fm = (
            f"tokens_input: {total_in}\n"
            f"tokens_output: {total_out}\n"
            f"cost_usd: {cost:.4f}\n"
        )

    filepath = reviews_dir / filename
    content = (
        f"---\n"
        f"repo: {owner}/{repo}\n"
        f"pr: {pr_number}\n"
        f"title: {pr_title}\n"
        f"requested_by: {result.requested_by}\n"
        f"date: {date_str}\n"
        f"url: https://github.com/{owner}/{repo}/pull/{pr_number}\n"
        f"pr_status: {pr_status}\n"
        f"{ts_fm}"
        f"{token_fm}"
        f"{files_fm}"
        f"---\n\n"
        + format_comment_markdown(
            result,
            f"https://github.com/{owner}/{repo}/pull/{pr_number}",
            pr_title=pr_title,
            pr_number=pr_number,
            owner_repo=f"{owner}/{repo}",
        )
    )
    filepath.write_text(content)
    return filepath
