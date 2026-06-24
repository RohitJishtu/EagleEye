"""Cockpit command — PR review dashboard."""
from __future__ import annotations

from typing import Annotated

import typer


def cockpit(
    open_browser: Annotated[bool, typer.Option("--open", help="Open in browser")] = False,
) -> None:
    """EagleEye Command Center — build the static reviews/index.html summary."""
    from ..presentation.html.dashboard import REVIEWS_DIR, build_dashboard
    from ..presentation.terminal import display_error, display_success

    if not REVIEWS_DIR.exists():
        display_error(f"No reviews directory found at '{REVIEWS_DIR}'. Run 'eagleeye review' first.")
        raise typer.Exit(1)
    out = build_dashboard()
    display_success(f"Cockpit built → {out}")
    if open_browser:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())
