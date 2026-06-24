"""GitHub PR data fetching — shared by CLI and review graphs."""

from __future__ import annotations

import re as _re
import time
from collections import deque
from typing import Any, Optional, TypedDict

_DIFF_WARN_THRESHOLD = 100_000

# SQL DDL files are naturally much larger than typical source code — a single
# migration script can contain dozens of CREATE TABLE statements. Use a higher
# cap so the agent doesn't see SQL files chopped mid-statement, which produces
# false-positive syntax errors (trailing comma, missing ADD keyword, etc.).
SQL_MAX_FILE_BYTES = 80_000


class PRFetchState(TypedDict, total=False):
    owner: str
    repo: str
    pr_number: int
    github_token: str
    max_files: int
    max_file_bytes: int
    max_total_bytes: int
    diff: str
    pr_metadata: dict
    file_list: list[str]
    full_file_contents: dict[str, str]
    base_file_contents: dict[str, str]
    structural_diff: Optional[Any]
    files_fetched: int
    files_total: int
    file_manifest: list
    search_window: deque[float]


def cap_for(filename: str, default: int) -> int:
    """Per-filetype byte cap for full-file fetching."""
    if filename.endswith(".sql"):
        return SQL_MAX_FILE_BYTES
    return default


def smart_truncate(content: str, filename: str, max_bytes: int) -> str:
    """Cut ``content`` at a safe boundary so agents don't see half-statements.

    Boundary rules:
      - ``.sql`` → last ``;`` before the cap.
      - ``.py`` → last blank line (``\\n\\n``), falling back to last newline.
      - other → last newline.

    If no safe boundary exists in the window, falls back to a hard byte cut.
    Always appends an explicit ``[truncated: N bytes omitted]`` marker so the
    LLM agent knows the cut happened and can avoid flagging boundary-induced
    syntax artifacts as bugs.
    """
    if len(content) <= max_bytes:
        return content

    window = content[:max_bytes]
    cut = -1

    if filename.endswith(".sql"):
        cut = window.rfind(";")
        if cut != -1:
            cut += 1  # keep the semicolon itself
            # Consume a trailing newline if present so the marker sits on its own line
            if cut < len(content) and content[cut] == "\n":
                cut += 1
    elif filename.endswith(".py"):
        blank = window.rfind("\n\n")
        if blank != -1:
            cut = blank + 2
        else:
            nl = window.rfind("\n")
            if nl != -1:
                cut = nl + 1
    else:
        nl = window.rfind("\n")
        if nl != -1:
            cut = nl + 1

    if cut <= 0:
        cut = max_bytes  # hard fallback

    truncated_body = content[:cut]
    omitted = len(content) - cut
    marker = f"\n-- [truncated: {omitted} bytes omitted by EagleEye file cap]\n"
    return truncated_body + marker


def fetch_pr_data(state: PRFetchState) -> dict:
    from ...presentation.terminal import display_info, display_phase, display_warning
    from .client import GitHubClient

    display_phase("Phase 1 · Fetching PR metadata & diff", "integrations/github/pr_fetch.py → fetch_pr_data")
    display_info(f"Fetching PR #{state['pr_number']} from {state['owner']}/{state['repo']}…")
    github = GitHubClient(state["github_token"])
    diff = github.get_pr_diff(state["owner"], state["repo"], state["pr_number"])
    metadata = github.get_pr_metadata(state["owner"], state["repo"], state["pr_number"])
    files = github.get_pr_files(state["owner"], state["repo"], state["pr_number"])
    github.close()

    if len(diff.encode()) > _DIFF_WARN_THRESHOLD:
        display_warning(f"Large diff ({len(diff.encode()) // 1024} KB). Review may be truncated.")

    return {
        "diff": diff,
        "pr_metadata": metadata,
        "file_list": [f["filename"] for f in files],
    }


def _fetch_one(args: tuple) -> tuple[str, str | None, int]:
    """Fetch a single file content — one GitHubClient per call for thread safety.
    Returns (filename, content_or_None, raw_byte_size_before_truncation).

    Truncation is boundary-aware: SQL files cut at the last ``;`` before the
    cap, Python files cut at the last blank line / newline. SQL also gets a
    larger default cap because DDL files are naturally bigger and naive cuts
    cause false-positive syntax findings.
    """
    owner, repo, filename, ref, token, max_file_bytes = args
    from .client import GitHubClient
    g = GitHubClient(token)
    try:
        content = g.get_file_content(owner, repo, filename, ref=ref)
        effective_cap = cap_for(filename, default=max_file_bytes)
        return filename, smart_truncate(content, filename, effective_cap), len(content)
    except Exception:
        return filename, None, 0
    finally:
        g.close()


def fetch_file_contents(state: PRFetchState) -> dict:
    import concurrent.futures

    from ...presentation.terminal import display_file_manifest, display_info, display_phase
    from .client import GitHubClient

    display_phase("Phase 2 · Reading changed files", "integrations/github/pr_fetch.py → fetch_file_contents")
    display_info("Fetching full file contents for cross-file analysis…")
    max_files = state.get("max_files", 30)
    max_file_bytes = state.get("max_file_bytes", 10_000)
    max_total_bytes = state.get("max_total_bytes", 150_000)
    github = GitHubClient(state["github_token"])
    repo_meta = github.get_repo_metadata(state["owner"], state["repo"])
    github.close()
    effective_branch = (
        state["pr_metadata"].get("head_sha")
        or state["pr_metadata"].get("base")
        or repo_meta.get("default_branch", "main")
    )

    files_total = len(state["file_list"])
    filenames = state["file_list"][:max_files]
    args_list = [
        (state["owner"], state["repo"], f, effective_branch, state["github_token"], max_file_bytes)
        for f in filenames
    ]

    full_file_contents: dict[str, str] = {}
    total_bytes = 0
    file_manifest: list[dict] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for filename, content, raw_size in pool.map(_fetch_one, args_list):
            if content is None:
                file_manifest.append({"file": filename, "status": "error", "size": 0})
            elif total_bytes >= max_total_bytes:
                file_manifest.append({"file": filename, "status": "byte_cap", "size": raw_size})
            else:
                full_file_contents[filename] = content
                total_bytes += len(content)
                effective_cap = cap_for(filename, default=max_file_bytes)
                status = "truncated" if raw_size > effective_cap else "ok"
                file_manifest.append({"file": filename, "status": status, "size": raw_size})

    for filename in state["file_list"][max_files:]:
        file_manifest.append({"file": filename, "status": "file_cap", "size": 0})

    display_file_manifest(file_manifest, total_bytes)

    files_fetched = len(full_file_contents)
    return {
        "full_file_contents": full_file_contents,
        "files_fetched": files_fetched,
        "files_total": files_total,
        "file_manifest": file_manifest,
    }


def fetch_base_files_and_diff_symbols(state: PRFetchState) -> dict:
    """Phase 2.5 — fetch base versions of changed Python files and compute the
    structural symbol diff (tree-sitter base vs head).

    Output keys: ``base_file_contents``, ``structural_diff``.

    Feature flag ``EAGLEEYE_STRUCTURAL_DIFF=0`` disables this phase entirely.
    On failure the phase returns ``structural_diff=None`` so downstream consumers
    fall back to the legacy regex/line-overlap paths transparently.
    """
    import concurrent.futures
    import os

    from ...presentation.terminal import display_info, display_phase, display_phase_skipped

    if os.environ.get("EAGLEEYE_STRUCTURAL_DIFF", "1") == "0":
        display_phase_skipped(
            "Phase 2.5 · Structural symbol diff",
            "Disabled via EAGLEEYE_STRUCTURAL_DIFF=0",
            "integrations/github/pr_fetch.py → fetch_base_files_and_diff_symbols",
        )
        return {"structural_diff": None, "base_file_contents": {}}

    display_phase(
        "Phase 2.5 · Structural symbol diff",
        "integrations/github/pr_fetch.py → fetch_base_files_and_diff_symbols",
    )

    head_files = {
        p: c for p, c in state.get("full_file_contents", {}).items() if p.endswith(".py")
    }
    py_changed = [f for f in state["file_list"] if f.endswith(".py")]
    if not py_changed:
        display_info("No Python files in PR — skipping structural diff.")
        return {"structural_diff": None, "base_file_contents": {}}

    pr_meta = state.get("pr_metadata", {}) or {}
    base_ref = pr_meta.get("base_sha") or pr_meta.get("base")
    if not base_ref:
        display_info("No base ref available — skipping structural diff.")
        return {"structural_diff": None, "base_file_contents": {}}

    max_files = state.get("max_files", 30)
    max_file_bytes = state.get("max_file_bytes", 10_000)
    targets = py_changed[:max_files]
    args_list = [
        (state["owner"], state["repo"], f, base_ref, state["github_token"], max_file_bytes)
        for f in targets
    ]

    base_files: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for filename, content, _raw in pool.map(_fetch_one, args_list):
            if content is not None:
                base_files[filename] = content

    from ...analysis.symbol_diff import compute_structural_diff

    sd = compute_structural_diff(base_files, head_files)
    display_info(
        f"Structural diff: {len(sd.changes)} change(s) across "
        f"{sd.files_analyzed} file(s) ({len(base_files)} base file(s) fetched)."
    )
    for c in sd.changes[:5]:
        sym = c.new or c.old
        if sym is not None:
            display_info(f"  · {c.kind} — {sym.signature.name}")

    return {"base_file_contents": base_files, "structural_diff": sd}


_SQL_DDL_RE = _re.compile(
    r'^[+\-]\s*(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:TRANSIENT\s+|VOLATILE\s+|TEMP\s+|SECURE\s+)?(?:TABLE|VIEW)'
    r'|ALTER\s+TABLE|DROP\s+(?:TABLE|VIEW))'
    r'\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([A-Z_][A-Z0-9_.]*)',
    _re.IGNORECASE | _re.MULTILINE,
)

_SQL_BLOCKLIST = {
    "RDS", "ODS_LS", "ODS", "BIGDATA", "STG", "STAGING", "TEMP", "TMP",
    "TABLE", "VIEW", "EXISTS", "IF",
}


def _extract_changed_symbols(diff: str) -> list[str]:
    """Extract changed Python function names and SQL DDL object names from a diff.

    For SQL objects, emits both the full qualified name (PLATFORM.ANALYTICS.MY_TABLE)
    and the leaf name (MY_TABLE) so GitHub Search catches references regardless
    of schema prefix. Objects whose leaf name is in _SQL_BLOCKLIST are skipped
    entirely (both FQN and leaf).
    Caps total at 10 symbols.
    """
    # Python: union of added + removed def names
    removed_py = set(_re.findall(
        r'^-\s*(?:async\s+)?def ([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', diff, _re.MULTILINE
    ))
    added_py = set(_re.findall(
        r'^\+\s*(?:async\s+)?def ([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', diff, _re.MULTILINE
    ))
    py_symbols = (removed_py | added_py) - {"__init__", "__repr__", "__str__"}

    # SQL: extract object names from DDL lines (+ and - lines)
    sql_fqns = {m.upper() for m in _SQL_DDL_RE.findall(diff)}
    sql_symbols: set[str] = set()
    for fqn in sql_fqns:
        leaf = fqn.split(".")[-1]
        if leaf in _SQL_BLOCKLIST:
            continue
        sql_symbols.add(fqn)
        sql_symbols.add(leaf)

    # Python fills slots first; SQL fills remainder up to cap of 10
    combined = list(py_symbols) + [s for s in sql_symbols if s not in py_symbols]
    return combined[:10]


def _throttled_search(github, search_window: deque, owner: str, repo: str, query: str) -> list[str]:
    """Call github.search_code with GitHub Search API rate-limit protection (30 req/min).

    Args:
        github: GitHubClient instance
        search_window: deque of timestamps for sliding-window rate-limit tracking
        owner, repo, query: search parameters
    """
    now = time.monotonic()
    while search_window and now - search_window[0] >= 60:
        search_window.popleft()
    if len(search_window) >= 28:
        sleep_for = 60 - (now - search_window[0]) + 0.5
        from ...presentation.terminal import display_info
        display_info(f"GitHub Search rate limit — waiting {sleep_for:.1f}s…")
        time.sleep(sleep_for)
    search_window.append(time.monotonic())
    return github.search_code(owner, repo, query)


def fetch_cross_repo_callers(state: PRFetchState) -> dict:
    """BFS 2-level caller search for symbols changed in this PR.

    Level 1 — direct callers: search the repo for each changed symbol name.
    Level 2 — indirect dependents: search for files that import from the modules
               where changes occurred (catches re-exports and facade wrappers).
    Budget: shared with fetch_files via state["max_files"] — no separate cap.
    """
    from ...presentation.terminal import display_info, display_phase, display_phase_skipped
    from .client import GitHubClient

    diff = state.get("diff", "")
    sd = state.get("structural_diff")
    structural_names = sd.changed_names()[:10] if sd is not None else []
    if structural_names:
        # Preferred path — tree-sitter base/head diff catches renames, sig
        # changes, decorator changes that the regex would miss.
        changed_symbols = structural_names
    else:
        changed_symbols = _extract_changed_symbols(diff)

    if not changed_symbols:
        display_phase_skipped(
            "Phase 3 · Blast radius — cross-repo caller search",
            "No Python functions or SQL objects detected in diff — caller search not needed",
            "integrations/github/pr_fetch.py → fetch_cross_repo_callers",
        )
        return {}

    display_phase("Phase 3 · Blast radius — cross-repo caller search", "integrations/github/pr_fetch.py → fetch_cross_repo_callers")

    # e.g. "src/utils.py" → "src.utils" (covers all modified files, not just deleted ones)
    modified_files = _re.findall(r'^diff --git a/(.+\.py) b/', diff, _re.MULTILINE)
    changed_modules = [
        f.replace("/", ".").removesuffix(".py")
        for f in modified_files[:3]
    ]

    already_fetched = len(state.get("full_file_contents", {}))
    remaining_budget = max(0, state.get("max_files", 30) - already_fetched)

    owner, repo = state["owner"], state["repo"]
    base_ref = (
        state["pr_metadata"].get("head_sha")
        or state["pr_metadata"].get("base", "main")
    )
    existing = set(state.get("full_file_contents", {}).keys())

    candidate_paths: list[str] = []

    github = GitHubClient(state["github_token"])
    try:
        display_info(
            f"L1 caller search — {len(changed_symbols)} changed symbol(s): {', '.join(changed_symbols)}"
        )
        l1_seen: set[str] = set()
        for symbol in changed_symbols:
            for path in _throttled_search(github, state["search_window"], owner, repo, symbol):
                if path.endswith((".py", ".sql")) and path not in existing and path not in l1_seen:
                    l1_seen.add(path)
                    candidate_paths.append(path)

        # Skipped if budget is already full from L1 (no point searching if we can't fetch more)
        if changed_modules and len(candidate_paths) < remaining_budget:
            display_info(
                f"L2 import search — {len(changed_modules)} module(s): {', '.join(changed_modules)}"
            )
            l2_seen: set[str] = set(l1_seen)
            for module in changed_modules:
                for query in (f"from {module} import", f"import {module}"):
                    for path in _throttled_search(github, state["search_window"], owner, repo, query):
                        if path.endswith(".py") and path not in existing and path not in l2_seen:
                            l2_seen.add(path)
                            candidate_paths.append(path)

        extra: dict[str, str] = {}
        for path in candidate_paths:
            if len(extra) >= remaining_budget:
                break
            try:
                content = github.get_file_content(owner, repo, path, ref=base_ref)
                extra[path] = content[:state.get("max_file_bytes", 10_000)]
            except Exception:
                pass

    finally:
        github.close()

    if not extra:
        return {}

    display_info(
        f"Blast radius: {len(extra)} file(s) fetched for {len(changed_symbols)} symbol(s) "
        f"(budget used: {len(extra)}/{remaining_budget}):"
    )
    for path in sorted(extra.keys()):
        display_info(f"  · {path}")

    return {"full_file_contents": {**state.get("full_file_contents", {}), **extra}}
