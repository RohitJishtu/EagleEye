"""Config sub-app and setup command."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from ..core.config import (
    ConfigError,
    load_config,
    show_config,
    write_config,
)
from ..presentation.terminal import (
    console,
    display_error,
    display_success,
)

config_app = typer.Typer(name="config", help="Manage EagleEye configuration.", no_args_is_help=True)


@config_app.command(name="show")
def config_show():
    """Show the resolved configuration (tokens are masked)."""
    try:
        config = load_config()
    except ConfigError as e:
        display_error(str(e))
        raise typer.Exit(1)

    from rich import box
    from rich.table import Table

    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Key", style="bold cyan", width=22)
    table.add_column("Value")

    info = show_config(config)
    for key, value in info.items():
        if key == "github_tokens":
            continue
        table.add_row(key, str(value))

    console.print(table)

    per_org = info.get("github_tokens")
    if per_org:
        console.print("[bold]Per-org tokens:[/bold]")
        for org, masked in per_org.items():
            console.print(f"  {org}: {masked}")


@config_app.command(name="init")
def config_init():
    """Interactively write ~/.eagleeye/config.yml."""
    console.print("[bold]EagleEye Configuration Setup[/bold]\n")
    github_token = typer.prompt("GitHub token (ghp_...)", hide_input=True)
    anthropic_key = typer.prompt("Anthropic API key (sk-ant-...)", hide_input=True)
    model = typer.prompt("Model", default="claude-sonnet-4-6")
    max_tokens = typer.prompt("Max tokens", default=8192)

    path = write_config(github_token.strip(), anthropic_key.strip(), model.strip(), int(max_tokens))
    display_success(f"Config written to {path}")


def setup():
    """Register EagleEye as an MCP server in Claude Code CLI.

    Run this once after installing. Only needs your GitHub token —
    no Anthropic API key required when using via Claude.
    """
    import subprocess

    console.print("[bold]EagleEye MCP Setup[/bold]\n")
    console.print("This registers EagleEye as an MCP server in Claude Code.")
    console.print("You only need a GitHub token — no Anthropic API key.\n")

    github_token = typer.prompt("GitHub token", hide_input=True)
    if not github_token.strip():
        display_error("GitHub token cannot be empty.")
        raise typer.Exit(1)

    # Remove existing registration if present
    subprocess.run(
        ["claude", "mcp", "remove", "eagleeye"],
        capture_output=True,
    )

    # Register with the new token
    result = subprocess.run(
        ["claude", "mcp", "add", "eagleeye", "eagleeye-mcp",
         "--env", f"GITHUB_TOKEN={github_token.strip()}"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        display_error(f"Setup failed: {result.stderr.strip() or result.stdout.strip()}")
        raise typer.Exit(1)

    display_success("EagleEye registered as an MCP server in Claude Code.")
    console.print("\n[dim]Next steps:[/dim]")
    console.print("  1. Open a new Claude Code session:  [bold]claude[/bold]")
    console.print("  2. Ask Claude to review a PR:       [bold]Review PR #5 in myorg/myrepo[/bold]")
    console.print("  3. Or read a repo:                  [bold]Give me an overview of myorg/myrepo[/bold]\n")
