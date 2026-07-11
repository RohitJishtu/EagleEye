"""Cockpit command — EagleEye Command Center dashboard."""
from __future__ import annotations

from typing import Annotated

import typer


def cockpit(
    open_browser: Annotated[bool, typer.Option("--open", help="Open in browser")] = False,
) -> None:
    """EagleEye Command Center — build reviews/index.html from saved reviews and evaluations."""
    from ..presentation.html.dashboard import EVALUATIONS_DIR, REVIEWS_DIR, build_dashboard
    from ..presentation.terminal import display_error, display_success

    has_reviews = REVIEWS_DIR.exists() and any(REVIEWS_DIR.rglob("*.md"))
    has_evals = EVALUATIONS_DIR.exists() and any(EVALUATIONS_DIR.rglob("eval-*.md"))
    if not has_reviews and not has_evals:
        display_error(
            "No saved reviews or evaluations found. "
            "Run `eagleeye review owner/repo 42` or `eagleeye evaluate owner/repo` first."
        )
        raise typer.Exit(1)
    out = build_dashboard()
    display_success(f"Cockpit built → {out}")
    if open_browser:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())
