"""Lineage sub-apps and edp_analyze command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..presentation.terminal import (
    console,
    display_error,
    display_info,
    display_success,
)
from ..cli._shared import _load_or_exit, _parse_repo, _parse_github_url

lineage_app = typer.Typer(name="lineage", help="Manage database lineage snapshots.", no_args_is_help=True)
ccms_app = typer.Typer(name="ccms", help="Manage lineage metadata snapshot (legacy alias).", hidden=True)


@lineage_app.command(name="check")
def lineage_check(
    object_name: Annotated[str, typer.Argument(help="Snowflake object name — e.g. ODS_LS.BI_APPS.WALLETSHARE_INFO")],
    depth: Annotated[int, typer.Option("--depth", "-d", help="Hops to traverse (1=direct, 2=two levels)")] = 2,
    direction: Annotated[str, typer.Option("--direction", help="upstream | downstream | both")] = "both",
):
    """Show upstream and downstream lineage for any Snowflake view or table.

    Reads from your local snapshot (DB_SNAPSHOT_PATH). No Snowflake connection needed.

    Examples:
      eagleeye lineage check ODS_LS.BI_APPS.WALLETSHARE_INFO
      eagleeye lineage check PLATFORM.ANALYTICS.USERS_TABLE --depth 3
      eagleeye lineage check MY_TABLE --direction downstream
    """
    import os

    ccms_path = os.environ.get("DB_SNAPSHOT_PATH") or os.environ.get("CCMS_SNAPSHOT_PATH")
    if not ccms_path:
        display_error(
            "No snapshot found. Set DB_SNAPSHOT_PATH in your .env:\n"
            "  DB_SNAPSHOT_PATH=~/.eagleeye/lineage/object_dependencies_snapshot.json\n"
            "Then run: eagleeye lineage refresh"
        )
        raise typer.Exit(1)

    ccms_path = os.path.expanduser(ccms_path)
    if not Path(ccms_path).exists():
        display_error(f"Snapshot not found at {ccms_path}. Run: eagleeye lineage refresh")
        raise typer.Exit(1)

    clean_name = object_name.strip('"').replace('"."', ".")

    display_info(f"Looking up {clean_name} in snapshot…")
    try:
        # Pandas-free BFS — reads snapshot JSON directly
        import json as _json
        _raw = _json.loads(Path(ccms_path).read_text(encoding="utf-8"))
        # Normalise: snapshot may be a list of dicts or a dict-of-lists
        if isinstance(_raw, dict):
            import itertools
            _rows = list(itertools.islice(_raw.values(), 1))[0] if _raw else []
            _rows = [dict(zip(_raw.keys(), vals)) for vals in zip(*_raw.values())]
        else:
            _rows = _raw
        _rows = [{k.upper(): v for k, v in r.items()} for r in _rows]

        def _bfs_pure(start: str, mode: str) -> list:
            visited, frontier, found = {start}, {start}, []
            for hop in range(1, depth + 1):
                if not frontier:
                    break
                nxt: set[str] = set()
                for obj in frontier:
                    if mode == "upstream":
                        matches = [r for r in _rows if str(r.get("OBJ", "")).upper() == obj]
                        for r in matches:
                            nb = str(r.get("REFERENCED_OBJECT_NAME", "")).upper()
                            if nb and nb not in visited:
                                visited.add(nb); nxt.add(nb)
                                found.append({"ObjectName": r.get("REFERENCED_OBJECT_NAME"),
                                              "ObjType": r.get("OBJ_TYPE"), "Schema": r.get("REFERENCED_SCHEMA"),
                                              "Db": r.get("REFERENCED_DATABASE"), "Hop": hop})
                    else:
                        matches = [r for r in _rows if str(r.get("REFERENCED_OBJECT_NAME", "")).upper() == obj]
                        for r in matches:
                            nb = str(r.get("OBJ", "")).upper()
                            if nb and nb not in visited:
                                visited.add(nb); nxt.add(nb)
                                found.append({"ObjectName": r.get("OBJ"), "ObjType": r.get("OBJ_TYPE"),
                                              "Schema": r.get("SCHEMA"), "Db": r.get("DB"), "Hop": hop})
                frontier = nxt
            return found

        root = clean_name.upper()
        result = {
            "upstream":   _bfs_pure(root, "upstream")   if direction in ("upstream",   "both") else [],
            "downstream": _bfs_pure(root, "downstream") if direction in ("downstream", "both") else [],
        }
    except Exception as e:
        display_error(f"Lineage lookup failed: {e}")
        raise typer.Exit(1)

    upstream   = result.get("upstream", [])
    downstream = result.get("downstream", [])

    if not upstream and not downstream:
        display_info(f"No lineage found for '{clean_name}' in the snapshot.")
        leaf = clean_name.split(".")[-1].upper()
        candidates = list({
            str(r.get("OBJ", "") or r.get("REFERENCED_OBJECT_NAME", ""))
            for r in _rows
            if leaf in str(r.get("OBJ", "")).upper() or leaf in str(r.get("REFERENCED_OBJECT_NAME", "")).upper()
        })[:8]
        if candidates:
            display_info(f"Similar objects found in snapshot (use exact name):")
            for c in sorted(candidates):
                display_info(f"  {c}")
        return

    from rich.table import Table
    from rich import box

    if upstream and direction in ("upstream", "both"):
        t = Table(title=f"⬆  Upstream — {clean_name}", box=box.SIMPLE, show_header=True)
        t.add_column("Object", style="cyan")
        t.add_column("Type", style="dim")
        t.add_column("Database")
        t.add_column("Schema")
        t.add_column("Hop", justify="right", style="dim")
        for row in sorted(upstream, key=lambda r: r.get("Hop", 0)):
            t.add_row(str(row.get("ObjectName", "")), str(row.get("ObjType", "")),
                      str(row.get("Db", "")), str(row.get("Schema", "")), str(row.get("Hop", "")))
        console.print(t)

    if downstream and direction in ("downstream", "both"):
        t = Table(title=f"⬇  Downstream — {clean_name}", box=box.SIMPLE, show_header=True)
        t.add_column("Object", style="green")
        t.add_column("Type", style="dim")
        t.add_column("Database")
        t.add_column("Schema")
        t.add_column("Hop", justify="right", style="dim")
        for row in sorted(downstream, key=lambda r: r.get("Hop", 0)):
            t.add_row(str(row.get("ObjectName", "")), str(row.get("ObjType", "")),
                      str(row.get("Db", "")), str(row.get("Schema", "")), str(row.get("Hop", "")))
        console.print(t)


def edp_analyze(
    repo: Annotated[str, typer.Argument(help="GitHub repo — owner/repo or full PR URL")],
    pr_number: Annotated[Optional[int], typer.Argument(help="PR number (omit if repo is a full URL)")] = None,
):
    """Show Snowflake lineage for a PR — what objects are read/written and their upstream/downstream chains."""
    import os

    from ..core.config import resolve_github_token

    config = _load_or_exit()

    # Accept full GitHub URL or owner/repo + pr_number
    parsed = _parse_github_url(repo)
    if parsed:
        owner, repo_name, pr_num = parsed
    elif pr_number:
        owner, repo_name = _parse_repo(repo)
        pr_num = pr_number
    else:
        display_error("Provide a full GitHub PR URL, or owner/repo + PR number.\n  eagleeye edp https://github.com/owner/repo/pull/42\n  eagleeye edp owner/repo 42")
        raise typer.Exit(1)

    token = resolve_github_token(owner, config)
    from ..integrations.github import GitHubClient
    from ..integrations.github.pr_fetch import fetch_file_contents as _fetch_files, fetch_pr_data as _fetch_pr

    display_info(f"Fetching PR #{pr_num} from {owner}/{repo_name}…")
    github = GitHubClient(token)
    try:
        state: dict = {
            "owner": owner, "repo": repo_name, "pr_number": pr_num,
            "github_token": token, "max_files": config.max_files,
            "max_file_bytes": config.max_file_bytes, "max_total_bytes": config.max_total_bytes,
            "diff": "", "pr_metadata": {}, "file_list": [], "full_file_contents": {},
            "files_fetched": 0, "files_total": 0, "file_manifest": [],
        }
        state.update(_fetch_pr(state))
        state.update(_fetch_files(state))
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)
    finally:
        github.close()

    diff  = state["diff"]
    files = state["full_file_contents"]

    from ..lineage import (
        enrich_extract_from_snapshot,
        extract_snowflake_usages,
        format_as_markdown as format_snowflake_lineage_markdown,
        infer_pr_lineage,
        is_available,
    )

    display_info("Extracting Snowflake object usages…")
    sf = extract_snowflake_usages(diff, files)

    ccms_path = os.environ.get("DB_SNAPSHOT_PATH") or os.environ.get("CCMS_SNAPSHOT_PATH")
    if ccms_path:
        ccms_path = os.path.expanduser(ccms_path)
        if is_available():
            display_info("Enriching with DB lineage snapshot…")
            sf = enrich_extract_from_snapshot(sf, ccms_path)
        else:
            display_info(
                "DB lineage enrichment skipped (install optional deps: pip install 'eagleeye[lineage]')."
            )

    infer_pr_lineage(sf.usages)

    sf_md = format_snowflake_lineage_markdown(sf)
    if not sf_md:
        display_info("No Snowflake object usages detected in this diff.")
        return

    from rich.panel import Panel
    from rich.markdown import Markdown
    console.print(Panel(Markdown(sf_md), title=f"[bold cyan]Snowflake Lineage — PR #{pr_num}[/bold cyan]", border_style="cyan"))


@lineage_app.command(name="refresh")
def lineage_refresh(
    out: Annotated[Optional[str], typer.Option("--out", help="Path to write snapshot JSON. Defaults to DB_SNAPSHOT_PATH env var.")] = None,
):
    """Fetch object dependency data from Snowflake and save as a local snapshot.

    Run this once (or on a schedule) to build the snapshot used by all PR reviews.
    Reviews read from DB_SNAPSHOT_PATH — they never query Snowflake directly.

    Requires DB_SF_USER and DB_SF_ACCOUNT env vars (or legacy CCMS_SF_USER / CCMS_SF_ACCOUNT).
    """
    import os

    from ..lineage import get_connection, refresh_metadata, require_lineage_refresh

    try:
        require_lineage_refresh()
    except ImportError as exc:
        display_error(str(exc))
        raise typer.Exit(1)

    # Support both new (DB_) and legacy (CCMS_) env var names
    user = os.environ.get("DB_SF_USER") or os.environ.get("CCMS_SF_USER")
    account = os.environ.get("DB_SF_ACCOUNT") or os.environ.get("CCMS_SF_ACCOUNT")
    if not user or not account:
        display_error("Set DB_SF_USER and DB_SF_ACCOUNT env vars (or legacy CCMS_SF_USER / CCMS_SF_ACCOUNT).")
        raise typer.Exit(1)

    snapshot_path = out or os.environ.get("DB_SNAPSHOT_PATH") or os.environ.get("CCMS_SNAPSHOT_PATH")
    if not snapshot_path:
        display_error(
            "Specify --out or set DB_SNAPSHOT_PATH env var\n"
            "  Example: DB_SNAPSHOT_PATH=~/.eagleeye/lineage/object_dependencies_snapshot.json"
        )
        raise typer.Exit(1)

    base_dir = str(Path(snapshot_path).expanduser().parent)

    display_info(f"Connecting to Snowflake ({account}) — browser SSO will open…")
    try:
        conn = get_connection(user=user, account=account)
    except Exception as e:
        display_error(f"Snowflake connection failed: {e}")
        raise typer.Exit(1)

    display_info("Fetching object_dependencies from snowflake.account_usage…")
    try:
        result = refresh_metadata(conn, dependencies=True, base_dir=base_dir)
        saved = result.get("dependencies", "")
        display_success(f"Database lineage snapshot saved → {saved}")
        display_info("Set DB_SNAPSHOT_PATH in your .env to use it in reviews.")
    except Exception as e:
        display_error(f"Snapshot refresh failed: {e}")
        raise typer.Exit(1)
    finally:
        conn.close()


@ccms_app.command(name="refresh")
def ccms_refresh(
    out: Annotated[Optional[str], typer.Option("--out", help="Path to write snapshot JSON. Defaults to CCMS_SNAPSHOT_PATH env var.")] = None,
):
    """[DEPRECATED] Use 'eagleeye lineage refresh' instead.

    Fetch object dependency data from Snowflake and save as a local snapshot.
    Requires CCMS_SF_USER and CCMS_SF_ACCOUNT env vars.
    """
    return lineage_refresh(out=out)
