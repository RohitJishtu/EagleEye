"""Health-check command for EagleEye install and configuration."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import typer

from ..core.config import ConfigError, _CONFIG_PATH, load_config
from ..core.paths import reviews_root
from ..presentation.terminal import console, display_error


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    required: bool = True


def _check_python() -> CheckResult:
    ok = sys.version_info >= (3, 11)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return CheckResult(
        "Python version",
        ok,
        f"{ver} (need >= 3.11)" if not ok else ver,
    )


def _check_github_token(online: bool) -> CheckResult:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        try:
            cfg = load_config()
            token = (cfg.github_token or "").strip()
        except ConfigError:
            token = ""
    if not token:
        return CheckResult(
            "GitHub token",
            False,
            "Set GITHUB_TOKEN in .env or ~/.eagleeye/config.yml",
        )
    if not online:
        return CheckResult("GitHub token", True, "present (use --online to verify API)")
    try:
        from ..integrations.github.client import GitHubClient

        client = GitHubClient(token)
        try:
            resp = client._get("/user")
            if resp.is_success:
                return CheckResult("GitHub token", True, "API reachable")
        finally:
            client.close()
        return CheckResult("GitHub token", False, "API check failed")
    except Exception as exc:
        return CheckResult("GitHub token", False, f"API check failed: {exc}")


def _check_anthropic() -> CheckResult:
    auth_mode = os.environ.get("AUTH_MODE", "direct").strip().lower()
    if auth_mode == "proxy":
        cid = os.environ.get("PROXY_CLIENT_ID", "").strip()
        secret = os.environ.get("PROXY_CLIENT_SECRET", "").strip()
        proxy_url = os.environ.get("EAGLEEYE_PROXY_URL", "").strip()
        if cid and secret and proxy_url:
            return CheckResult("Anthropic / proxy", True, f"AUTH_MODE=proxy ({proxy_url})")
        try:
            cfg = load_config()
            if cfg.proxy_client_id and cfg.proxy_client_secret and cfg.proxy_url:
                return CheckResult("Anthropic / proxy", True, f"AUTH_MODE=proxy ({cfg.proxy_url})")
        except ConfigError:
            pass
        return CheckResult(
            "Anthropic / proxy",
            False,
            "Set PROXY_CLIENT_ID, PROXY_CLIENT_SECRET, EAGLEEYE_PROXY_URL",
        )

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        try:
            cfg = load_config()
            key = (cfg.anthropic_api_key or "").strip()
        except ConfigError:
            key = ""
    if not key:
        return CheckResult(
            "Anthropic API key",
            False,
            "Set ANTHROPIC_API_KEY or use AUTH_MODE=proxy",
        )
    return CheckResult("Anthropic API key", True, "present")


def _check_config_file() -> CheckResult:
    if _CONFIG_PATH.exists():
        return CheckResult("Config file", True, str(_CONFIG_PATH))
    if os.environ.get("GITHUB_TOKEN") and (
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("AUTH_MODE") == "proxy"
    ):
        return CheckResult("Config file", True, "using environment variables only")
    return CheckResult(
        "Config file",
        False,
        f"Missing {_CONFIG_PATH} — run: eagleeye config init",
    )


def _check_reviews_writable() -> CheckResult:
    root = reviews_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, prefix=".doctor-", delete=True):
            pass
        return CheckResult("Reviews directory", True, str(root))
    except OSError as exc:
        return CheckResult("Reviews directory", False, f"Cannot write to {root}: {exc}")


def _check_imports() -> CheckResult:
    try:
        importlib.import_module("eagleeye")
        importlib.import_module("tree_sitter")
        importlib.import_module("tree_sitter_python")
        return CheckResult("Core imports", True, "eagleeye + tree-sitter OK")
    except ImportError as exc:
        return CheckResult("Core imports", False, str(exc))


def _check_lineage_optional() -> CheckResult:
    try:
        importlib.import_module("pandas")
        return CheckResult("Lineage extra (pandas)", True, "installed", required=False)
    except ImportError:
        return CheckResult(
            "Lineage extra (pandas)",
            True,
            "not installed — optional: pip install -e '.[lineage]'",
            required=False,
        )


def _check_reference_indexes() -> CheckResult:
    from ..storage.reference import INDEX_DIR, load_index

    if not INDEX_DIR.exists():
        return CheckResult(
            "Reference indexes",
            True,
            "none built (optional: eagleeye reference build owner/repo)",
            required=False,
        )
    indexes: list[str] = []
    for path in sorted(INDEX_DIR.glob("*__*.json")):
        name = path.stem.replace("__", "/")
        idx = load_index(*name.split("/", 1)) if "/" in name else None
        if idx:
            indexes.append(f"{idx.owner}/{idx.repo} ({idx.files_indexed} files, {idx.built_at[:10]})")
    detail = "; ".join(indexes) if indexes else "directory exists, no indexes"
    return CheckResult("Reference indexes", True, detail, required=False)


def doctor(
    online: bool = typer.Option(False, "--online", help="Ping GitHub API to verify token"),
) -> None:
    """Check EagleEye install, configuration, and optional dependencies."""
    from rich import box
    from rich.table import Table

    checks: list[CheckResult] = [
        _check_python(),
        _check_github_token(online),
        _check_anthropic(),
        _check_config_file(),
        _check_reviews_writable(),
        _check_imports(),
        _check_lineage_optional(),
        _check_reference_indexes(),
    ]

    table = Table(title="EagleEye Doctor", box=box.ROUNDED, show_header=True)
    table.add_column("Check", style="bold")
    table.add_column("Status", width=8)
    table.add_column("Detail")

    failed_required = False
    for check in checks:
        icon = "[green]✅[/green]" if check.passed else "[red]❌[/red]"
        if not check.passed and check.required:
            failed_required = True
        table.add_row(check.name, icon, check.detail)

    console.print(table)

    if failed_required:
        display_error("One or more required checks failed. Fix the items above and re-run.")
        raise typer.Exit(1)

    console.print("\n[green]All required checks passed.[/green] Run: [bold]eagleeye review owner/repo 42[/bold]")
