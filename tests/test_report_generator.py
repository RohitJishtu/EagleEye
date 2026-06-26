"""Tests for report_generator helpers."""
from eagleeye.report_generator import _parse_frontmatter, _fmt, _render_lineage_tree, _parse_sections


def test_parse_frontmatter_url_preserved():
    content = "---\nurl: https://github.com/owner/repo/pull/42\ntitle: My PR\n---\nBody"
    fm, _ = _parse_frontmatter(content)
    assert fm["url"] == "https://github.com/owner/repo/pull/42"


def test_parse_frontmatter_simple_values():
    content = "---\ntitle: My PR\nrisk: high\n---\nBody"
    fm, body = _parse_frontmatter(content)
    assert fm["title"] == "My PR"
    assert fm["risk"] == "high"
    assert body == "Body"


def test_parse_frontmatter_no_frontmatter():
    content = "Just a plain body"
    fm, body = _parse_frontmatter(content)
    assert fm == {}
    assert body == "Just a plain body"


def test_fmt_escapes_html_before_transforms():
    result = _fmt("<script>alert('xss')</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_fmt_backtick_still_works_after_escape():
    result = _fmt("`some_function()`")
    assert "<code>some_function()</code>" in result


def test_fmt_bold_still_works_after_escape():
    result = _fmt("**important**")
    assert "<strong>important</strong>" in result


def test_render_lineage_tree_single_node():
    html = _render_lineage_tree("SCHEMA.TABLE_A")
    assert "<details" in html or "<div" in html
    assert "SCHEMA.TABLE_A" in html


def test_render_lineage_tree_nested():
    text = "SCHEMA.TABLE_A\n  SCHEMA.TABLE_B\n    SCHEMA.TABLE_C"
    html = _render_lineage_tree(text)
    assert html.count("<details") >= 1
    assert "SCHEMA.TABLE_B" in html
    assert "SCHEMA.TABLE_C" in html


def test_render_lineage_tree_empty():
    assert _render_lineage_tree("") == ""
    assert _render_lineage_tree("   ") == ""


def test_render_lineage_tree_escapes_html():
    html = _render_lineage_tree("SCHEMA.<TABLE>")
    assert "<TABLE>" not in html
    assert "&lt;TABLE&gt;" in html


# ---------------------------------------------------------------------------
# _parse_sections
# ---------------------------------------------------------------------------

def test_parse_sections_ignores_heading_inside_code_block():
    text = (
        "### Real Section\n"
        "Some content here.\n"
        "\n"
        "```sql\n"
        "### This looks like a heading but is inside a code block\n"
        "SELECT * FROM table;\n"
        "```\n"
        "\n"
        "More content after the code block.\n"
        "\n"
        "### Second Section\n"
        "Second content.\n"
    )
    sections = _parse_sections(text)
    assert "Real Section" in sections
    assert "Second Section" in sections
    assert "This looks like a heading but is inside a code block" not in sections
    assert "SELECT * FROM table" in sections["Real Section"]


def test_parse_sections_normal_headings_still_work():
    text = "### Summary\nThis is the summary.\n\n### Findings\nThese are findings.\n"
    sections = _parse_sections(text)
    assert list(sections.keys()) == ["Summary", "Findings"]
    assert "This is the summary." in sections["Summary"]
