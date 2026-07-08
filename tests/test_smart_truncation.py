"""Tests for smart_truncate — boundary-aware file truncation.

The naive ``content[:max_bytes]`` cut creates false-positive syntax errors
when SQL files get sliced mid-statement (e.g. an ALTER TABLE with a trailing
comma that LOOKS malformed but actually continues past the cut).

These tests pin the desired behaviour:
  - Files that fit are returned unchanged.
  - SQL files cut at the last ``;`` (statement boundary) before the cap.
  - Python files cut at the last blank line, falling back to last newline.
  - Other files cut at the last newline.
  - A truncation marker is appended so the agent knows the cut happened.
  - SQL files use a higher byte cap than other files (DDL is naturally bigger).
"""

from __future__ import annotations

from eagleeye.graphs.pr_review import (
    SQL_MAX_FILE_BYTES,
    cap_for,
    smart_truncate,
)

# ---------------------------------------------------------------------------
# Pass-through when content fits
# ---------------------------------------------------------------------------


def test_no_truncation_when_content_fits():
    content = "SELECT 1;\n"
    out = smart_truncate(content, "a.sql", max_bytes=1000)
    assert out == content


# ---------------------------------------------------------------------------
# SQL — cut at last semicolon
# ---------------------------------------------------------------------------


def test_sql_truncates_at_last_semicolon_before_cap():
    content = (
        "CREATE TABLE a (id INT);\n"
        "CREATE TABLE b (id INT);\n"
        "CREATE TABLE c (\n"
        "    id INT,\n"
        "    name VARCHAR(100)\n"
        ");\n"
    )
    # Cap chosen to land inside the third table — must back up to the previous `;`.
    out = smart_truncate(content, "schemas.sql", max_bytes=60)
    assert "CREATE TABLE a" in out
    assert "CREATE TABLE b" in out
    # Third table must NOT appear partially — we'd rather drop it than half-show it.
    assert "CREATE TABLE c" not in out
    assert "[truncated" in out


def test_sql_truncation_falls_back_when_no_semicolon_in_window():
    # No `;` exists before the cap — fall back to last newline, then to a
    # hard cut. Either way, never silently leave a mid-statement view.
    content = "CREATE TABLE c (\n    id INT,\n    name VARCHAR(50),\n    region VARCHAR(50)\n);\n"
    out = smart_truncate(content, "huge.sql", max_bytes=40)
    # We accept any of: ends at newline, ends at hard cut, but MUST contain the marker.
    assert "[truncated" in out


# ---------------------------------------------------------------------------
# Python — cut at blank line, fall back to newline
# ---------------------------------------------------------------------------


def test_python_truncates_at_blank_line_boundary():
    content = (
        "def a():\n"
        "    return 1\n"
        "\n"
        "def b():\n"
        "    return 2\n"
        "\n"
        "def c():\n"
        "    return 3\n"
    )
    out = smart_truncate(content, "m.py", max_bytes=40)
    assert "def a" in out
    # Should NOT include a partial def c
    assert "def c" not in out or "return 3" in out  # full or absent, not partial
    assert "[truncated" in out


# ---------------------------------------------------------------------------
# Other files — cut at last newline
# ---------------------------------------------------------------------------


def test_generic_file_truncates_at_newline():
    content = "line one\nline two\nline three that is somewhat longer\nline four\n"
    out = smart_truncate(content, "notes.md", max_bytes=20)
    # Must not end mid-line.
    body = out.split("\n[truncated")[0]
    assert body.endswith("\n") or body == ""
    assert "[truncated" in out


# ---------------------------------------------------------------------------
# Truncation marker
# ---------------------------------------------------------------------------


def test_marker_reports_omitted_byte_count():
    content = "x" * 1000 + "\n"
    out = smart_truncate(content, "blob.txt", max_bytes=100)
    assert "[truncated" in out
    # Marker should mention how many bytes were dropped (roughly)
    assert "bytes omitted" in out or "more bytes" in out


# ---------------------------------------------------------------------------
# Per-filetype cap
# ---------------------------------------------------------------------------


def test_sql_cap_is_higher_than_default():
    # SQL DDL is naturally larger — SQL files get a bigger default budget.
    sql_cap = cap_for("schemas.sql", default=10_000)
    py_cap = cap_for("module.py", default=10_000)
    assert sql_cap > py_cap
    assert sql_cap == SQL_MAX_FILE_BYTES


def test_cap_for_unknown_extension_uses_default():
    assert cap_for("README.md", default=10_000) == 10_000
    assert cap_for("config.yml", default=10_000) == 10_000
