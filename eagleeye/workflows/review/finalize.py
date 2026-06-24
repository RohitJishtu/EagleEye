"""Post-review finalization: GitHub comment, file save, and side effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...graphs.pr_review import PRReviewState


def post_github_comment(state: PRReviewState) -> dict:
    if not state.get("post_comment"):
        return {}
    from ...presentation.terminal import display_info
    from ...integrations.github import GitHubClient
    from .formatting import format_comment_markdown

    display_info("Posting review comment to GitHub…")
    github = GitHubClient(state["github_token"])
    comment_body = format_comment_markdown(
        state["result"], state["pr_metadata"].get("html_url", "")
    )
    github.post_pr_comment(state["owner"], state["repo"], state["pr_number"], comment_body)
    github.close()
    display_info("Comment posted.")
    return {}


def save_review_file(state: PRReviewState) -> dict:
    from ...presentation.terminal import display_info, display_phase
    from ...presentation.html.report import process as _generate_html
    from .persist import save_review

    display_phase(
        "Phase 7 · Saving review & generating HTML report",
        "workflows/review/finalize.py → save_review_file",
    )
    saved_path = None
    try:
        saved_path = save_review(
            state["owner"],
            state["repo"],
            state["pr_number"],
            state["pr_metadata"].get("title", ""),
            state["result"],
            file_manifest=state.get("file_manifest", []),
            token_usage=state.get("token_usage"),
            pr_status=state["pr_metadata"].get("pr_status", ""),
        )
        display_info(f"Review saved to {saved_path}")
        html_path = _generate_html(saved_path, schema_impact=state.get("schema_impact"))
        display_info(f"HTML report  → {html_path}")
    except Exception as _e:
        display_info(f"Warning: could not save review — {_e}")

    # Auto-rebuild cockpit dashboard so index.html stays current
    try:
        from ...presentation.html.dashboard import build_dashboard
        build_dashboard()
        display_info("Cockpit updated → reviews/index.html")
    except Exception:
        pass

    # Register feature consumers in catalog (non-blocking)
    try:
        from ...storage.catalog import (
            add_consumers_from_review,
            get_catalogs_for_org,
            refresh_catalog,
        )
        owner = state["owner"]
        repo  = state["repo"]
        reviewing_repo = f"{owner}/{repo}"
        for catalog in get_catalogs_for_org(owner):
            if catalog.feature_store_repo == reviewing_repo:
                # Reviewing the feature store itself — refresh catalog
                from ...integrations.github import GitHubClient
                github = GitHubClient(state["github_token"])
                try:
                    refresh_catalog(owner, repo, github)
                    display_info("Feature catalog refreshed.")
                finally:
                    github.close()
            else:
                fs_owner, fs_repo = catalog.feature_store_repo.split("/", 1)
                add_consumers_from_review(
                    fs_owner, fs_repo,
                    reviewing_repo,
                    state.get("diff", ""),
                    state.get("full_file_contents", {}),
                )
    except Exception:
        pass

    # Append to PR history index (non-blocking)
    try:
        from ...storage.history import PRHistoryEntry, add_entry
        result = state.get("result")
        add_entry(
            state["owner"],
            state["repo"],
            PRHistoryEntry(
                pr_number=state["pr_number"],
                title=state["pr_metadata"].get("title", ""),
                merged_at=state["pr_metadata"].get("merged_at", ""),
                author=state["pr_metadata"].get("author", ""),
                files_changed=state.get("file_list", []),
                body_snippet=(state["pr_metadata"].get("body") or "")[:300],
                verdict=result.overall_verdict if result else None,
                risk_level=result.risk_level if result else None,
                summary=result.summary[:200] if result else None,
            ),
        )
    except Exception:
        pass

    return {}
