"""Cockpit command — EagleEye Command Center dashboard."""
from __future__ import annotations

from typing import Annotated

import typer


def cockpit(
    open_browser: Annotated[bool, typer.Option("--open", help="Open in browser")] = False,
    host: Annotated[str, typer.Option(help="Cockpit bind address")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Cockpit port")] = 8765,
    serve_live: Annotated[
        bool,
        typer.Option("--serve/--build-only", help="Serve live run/status APIs"),
    ] = True,
) -> None:
    """Launch the EagleEye Command Center and its live review APIs."""
    from ..presentation.html.dashboard import build_dashboard
    from ..presentation.terminal import display_info, display_success

    out = build_dashboard()
    display_success(f"Cockpit built → {out}")
    if not serve_live:
        if open_browser:
            import webbrowser

            webbrowser.open(out.resolve().as_uri())
        return

    url = f"http://{host}:{port}"
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    display_info(f"Cockpit live → {url} (press Ctrl+C to stop)")
    from ..cockpit_server import serve

    try:
        serve(host=host, port=port)
    except KeyboardInterrupt:
        display_info("Cockpit stopped.")
