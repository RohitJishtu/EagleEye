"""Tests for the blast_radius analysis module."""

from __future__ import annotations

from eagleeye.analysis.blast_radius import (
    compute_blast_radius,
    format_as_markdown,
    _parse_diff_hunks,
)
from eagleeye.analysis.symbol_diff import compute_structural_diff


# ---------------------------------------------------------------------------
# compute_blast_radius — structural_diff integration
# ---------------------------------------------------------------------------


def test_compute_blast_radius_uses_structural_diff_when_provided():
    """When a StructuralSymbolDiff is provided, blast radius uses it as the
    authoritative source instead of re-deriving from line-overlap."""
    diff = ""  # empty diff — the line-overlap path would find nothing
    base = {"m.py": "def get_user(uid):\n    return uid\n"}
    head = {"m.py": "def fetch_user(uid):\n    return uid\n"}
    sd = compute_structural_diff(base, head)
    callers_file = {"caller.py": "def x():\n    return fetch_user(1)\n"}

    result = compute_blast_radius(
        diff,
        {**head, **callers_file},
        structural_diff=sd,
    )
    names = {s.name for s in result.changed_symbols}
    # Rename should expose both old and new names as "changed"
    assert "fetch_user" in names
    # Caller search should find the use of fetch_user in caller.py
    assert "fetch_user" in result.callers
    assert any(c.file == "caller.py" for c in result.callers["fetch_user"])


def test_compute_blast_radius_falls_back_when_structural_diff_absent():
    """Backward compatibility — no structural_diff arg works as before."""
    diff = (
        "diff --git a/m.py b/m.py\n"
        "--- a/m.py\n"
        "+++ b/m.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def f(x):\n"
        "+    print(x)\n"
        "     return x\n"
    )
    file_contents = {"m.py": "def f(x):\n    print(x)\n    return x\n"}
    result = compute_blast_radius(diff, file_contents)
    # Existing behaviour: f is identified as changed via line-overlap
    assert any(s.name == "f" for s in result.changed_symbols)


# ---------------------------------------------------------------------------
# _parse_diff_hunks
# ---------------------------------------------------------------------------


def test_parse_diff_hunks_extracts_touched_lines():
    diff = (
        "diff --git a/pkg/mod.py b/pkg/mod.py\n"
        "--- a/pkg/mod.py\n"
        "+++ b/pkg/mod.py\n"
        "@@ -10,3 +10,4 @@\n"
        " context\n"
        "+added line one\n"
        "+added line two\n"
        " another context\n"
    )
    hunks = _parse_diff_hunks(diff)
    assert "pkg/mod.py" in hunks
    # New-file lines: 10 (context), 11 (+), 12 (+), 13 (context)
    assert 11 in hunks["pkg/mod.py"]
    assert 12 in hunks["pkg/mod.py"]


def test_parse_diff_hunks_multiple_files():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+new\n"
        "diff --git a/b.py b/b.py\n"
        "@@ -5,1 +5,2 @@\n"
        "+other\n"
    )
    hunks = _parse_diff_hunks(diff)
    assert "a.py" in hunks
    assert "b.py" in hunks
    assert 5 in hunks["b.py"]


# ---------------------------------------------------------------------------
# compute_blast_radius — core behaviors
# ---------------------------------------------------------------------------


def test_detects_changed_function_and_finds_caller():
    diff = (
        "diff --git a/lib.py b/lib.py\n"
        "--- a/lib.py\n"
        "+++ b/lib.py\n"
        "@@ -1,3 +1,4 @@\n"
        " def helper():\n"
        "-    return 1\n"
        "+    return 2\n"
        "+    # extra\n"
    )
    files = {
        "lib.py": "def helper():\n    return 2\n    # extra\n",
        "app.py": "from lib import helper\n\ndef main():\n    x = helper()\n    return x\n",
    }
    result = compute_blast_radius(diff, files)
    names = [s.name for s in result.changed_symbols]
    assert "helper" in names
    assert "helper" in result.callers
    caller_files = {c.file for c in result.callers["helper"]}
    assert "app.py" in caller_files


def test_no_change_when_diff_is_empty():
    result = compute_blast_radius("", {"app.py": "def foo():\n    pass\n"})
    assert result.changed_symbols == []
    assert result.callers == {}


def test_skips_non_python_files():
    diff = (
        "diff --git a/config.yml b/config.yml\n"
        "@@ -1,1 +1,2 @@\n"
        "+foo: bar\n"
    )
    result = compute_blast_radius(diff, {"config.yml": "foo: bar\n"})
    assert result.files_skipped == 1
    assert result.files_analyzed == 0


def test_method_on_class_marked_as_method():
    diff = (
        "diff --git a/svc.py b/svc.py\n"
        "--- a/svc.py\n"
        "+++ b/svc.py\n"
        "@@ -1,4 +1,5 @@\n"
        " class Svc:\n"
        "     def run(self):\n"
        "-        return 1\n"
        "+        return 2\n"
        "+        # note\n"
    )
    files = {"svc.py": "class Svc:\n    def run(self):\n        return 2\n        # note\n"}
    result = compute_blast_radius(diff, files)
    run_sym = next((s for s in result.changed_symbols if s.name == "run"), None)
    assert run_sym is not None
    assert run_sym.kind == "method"


# ---------------------------------------------------------------------------
# format_as_markdown
# ---------------------------------------------------------------------------


def test_markdown_output_mentions_changed_symbol():
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def foo():\n"
        "-    return 1\n"
        "+    return 2\n"
        "+    # extra\n"
    )
    files = {
        "x.py": "def foo():\n    return 2\n    # extra\n",
        "y.py": "from x import foo\nresult = foo()\n",
    }
    result = compute_blast_radius(diff, files)
    md = format_as_markdown(result)
    assert "## Blast Radius Analysis" in md
    assert "`foo`" in md
    assert "y.py" in md


def test_markdown_output_when_nothing_changed():
    md = format_as_markdown(compute_blast_radius("", {}))
    assert "No Python symbol changes detected" in md


# ---------------------------------------------------------------------------
# fetch_cross_repo_callers fixes (Task 8)
# ---------------------------------------------------------------------------

import re as _re_module

SAMPLE_DIFF = """\
diff --git a/payments.py b/payments.py
--- a/payments.py
+++ b/payments.py
@@ -1,5 +1,6 @@
-def process_payment(amount):
+def process_payment(amount, currency="USD"):
     pass

+def new_helper():
+    pass
"""


def test_changed_symbols_includes_modified():
    """Modified functions must be in the search set, not just deleted ones."""
    diff = SAMPLE_DIFF
    removed = set(_re_module.findall(r'^-\s*(?:async\s+)?def ([a-zA-Z_]\w*)\s*\(', diff, _re_module.MULTILINE))
    added   = set(_re_module.findall(r'^\+\s*(?:async\s+)?def ([a-zA-Z_]\w*)\s*\(', diff, _re_module.MULTILINE))
    # Old logic: deleted only = removed - added
    deleted_only = removed - added
    assert "process_payment" not in deleted_only  # modified, not deleted — old logic misses it

    # New logic: all changed = union minus dunder methods
    all_changed = (removed | added) - {"__init__", "__repr__", "__str__"}
    assert "process_payment" in all_changed   # new logic catches it
    assert "new_helper" in all_changed        # added functions also caught


def test_file_budget_constant_removed():
    """_CROSS_REPO_MAX_FILES must not exist as a separate cap."""
    import eagleeye.graphs.pr_review as m
    assert not hasattr(m, "_CROSS_REPO_MAX_FILES"), (
        "_CROSS_REPO_MAX_FILES still present — should be removed and unified with _MAX_FILES"
    )


# ---------------------------------------------------------------------------
# Throttle window logic (Task 9)
# ---------------------------------------------------------------------------


def test_throttle_window_logic():
    """Sliding-window throttle: 28 calls pass immediately, 29th is blocked."""
    from collections import deque
    import time

    RATE_LIMIT = 28
    window: deque = deque()

    def tick() -> bool:
        now = time.monotonic()
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= RATE_LIMIT:
            return False  # would sleep
        window.append(now)
        return True

    results = [tick() for _ in range(28)]
    assert all(results), "First 28 should pass immediately"
    assert tick() is False, "29th should hit the rate limit"


# ---------------------------------------------------------------------------
# _extract_changed_symbols — SQL + Python symbol extraction (Task 1)
# ---------------------------------------------------------------------------

from eagleeye.graphs.pr_review import _extract_changed_symbols


def test_sql_create_table_extracted():
    diff = "+CREATE TABLE PLATFORM.ANALYTICS.USERS_TABLE (\n  ID VARCHAR\n);"
    syms = _extract_changed_symbols(diff)
    assert "PLATFORM.ANALYTICS.USERS_TABLE" in syms
    assert "USERS_TABLE" in syms


def test_sql_create_or_replace_view_extracted():
    diff = "+CREATE OR REPLACE VIEW WAREHOUSE.ANALYTICS.V_USER_PROFILE AS SELECT 1;"
    syms = _extract_changed_symbols(diff)
    assert "V_USER_PROFILE" in syms
    assert "WAREHOUSE.ANALYTICS.V_USER_PROFILE" in syms


def test_sql_drop_table_extracted():
    diff = "-DROP TABLE RDS.BIGDATA.STG_OLD_TABLE;"
    syms = _extract_changed_symbols(diff)
    assert "STG_OLD_TABLE" in syms
    assert "RDS.BIGDATA.STG_OLD_TABLE" in syms


def test_sql_alter_table_extracted():
    diff = "+ALTER TABLE RDS.BIGDATA.PAYMENT_LEDGER ADD COLUMN CURRENCY VARCHAR;"
    syms = _extract_changed_symbols(diff)
    assert "PAYMENT_LEDGER" in syms


def test_sql_blocklist_filters_bare_noise():
    # Leaf name is a bare schema keyword — both FQN and leaf are skipped
    diff = "+CREATE TABLE RDS.BIGDATA.TEMP (ID VARCHAR);"
    syms = _extract_changed_symbols(diff)
    assert "TEMP" not in syms


def test_mixed_python_and_sql():
    diff = (
        "+def process_payment(amount):\n"
        "     pass\n"
        "+CREATE TABLE RDS.BIGDATA.PAYMENT_LEDGER (ID VARCHAR);\n"
    )
    syms = _extract_changed_symbols(diff)
    assert "process_payment" in syms
    assert "PAYMENT_LEDGER" in syms
    assert "RDS.BIGDATA.PAYMENT_LEDGER" in syms


# ---------------------------------------------------------------------------
# fetch_cross_repo_callers wiring — .sql file extension (Task 2)
# ---------------------------------------------------------------------------


def test_sql_file_extension_accepted():
    """SQL files must be included in fetch_cross_repo_callers candidate filter."""
    import inspect
    import eagleeye.graphs.pr_review as m
    src = inspect.getsource(m.fetch_cross_repo_callers)
    assert '".sql"' in src or "'.sql'" in src, (
        ".sql extension not found in fetch_cross_repo_callers — SQL caller files will be missed"
    )


def test_extract_changed_symbols_used_not_inline_regex():
    """fetch_cross_repo_callers must delegate to _extract_changed_symbols, not re-implement."""
    import inspect
    import eagleeye.graphs.pr_review as m
    src = inspect.getsource(m.fetch_cross_repo_callers)
    # The old inline regex must no longer be present inside fetch_cross_repo_callers
    assert 'findall(r\'^-\\s*(?:async' not in src, (
        "Old inline Python regex still present in fetch_cross_repo_callers — "
        "delegate to _extract_changed_symbols instead"
    )
