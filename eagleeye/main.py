"""EagleEye CLI — AI-powered code review for tech leads."""
from __future__ import annotations

import typer

from .cli.catalog import catalog_app
from .cli.cockpit_cmd import cockpit
from .cli.config_cmds import config_app, config_init, config_show, setup
from .cli.context import context_app
from .cli.history import history_app
from .cli.lineage import ccms_app, edp_analyze, lineage_app
from .cli.reference import reference_app
from .cli.review import list_prs, read, read_all, review, scan, serve
from .cli.schedule import schedule_app

app = typer.Typer(
    name="eagleeye",
    help="EagleEye — AI-powered code review CLI for tech leads.\n\n"
         "Powered by Claude. Requires GITHUB_TOKEN and ANTHROPIC_API_KEY.",
    add_completion=False,
    no_args_is_help=True,
)

# ── Sub-apps ──────────────────────────────────────────────────────────────────
app.add_typer(config_app,    name="config")
app.add_typer(context_app,   name="context")
app.add_typer(lineage_app,   name="lineage")
app.add_typer(ccms_app,      name="ccms",      hidden=True)
app.add_typer(catalog_app,   name="catalog")
app.add_typer(reference_app, name="reference")
app.add_typer(history_app,   name="history")
app.add_typer(schedule_app,  name="schedule")

# ── Top-level commands ────────────────────────────────────────────────────────
app.command(name="review")(review)
app.command(name="read")(read)
app.command(name="read-all")(read_all)
app.command(name="scan")(scan)
app.command(name="list-prs")(list_prs)
app.command(name="serve")(serve)
app.command(name="setup")(setup)
app.command(name="edp")(edp_analyze)

# config sub-commands also exposed at top level for backward compat
app.command(name="config-show", hidden=True)(config_show)
app.command(name="config-init", hidden=True)(config_init)

# Cockpit dashboard
app.command()(cockpit)


if __name__ == "__main__":
    app()
