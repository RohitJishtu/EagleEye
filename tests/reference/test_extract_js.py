from pathlib import Path

from eagleeye.reference_store import extract_js, extract_ts

FIXTURES = Path(__file__).parent / "fixtures"


def _names_with_kind(result, kind):
    return [name for name, m in result if m.kind == kind]


def test_extract_ts_finds_function_def():
    content = (FIXTURES / "sample.ts").read_text()
    result = extract_ts(content, "src/server.ts")
    assert "startServer" in _names_with_kind(result, "js.def")


def test_extract_ts_finds_class_def():
    content = (FIXTURES / "sample.ts").read_text()
    result = extract_ts(content, "src/server.ts")
    assert "ServerWrapper" in _names_with_kind(result, "js.def")


def test_extract_ts_finds_top_level_const():
    content = (FIXTURES / "sample.ts").read_text()
    result = extract_ts(content, "src/server.ts")
    assert "runServer" in _names_with_kind(result, "js.def")


def test_extract_ts_finds_calls():
    content = (FIXTURES / "sample.ts").read_text()
    result = extract_ts(content, "src/server.ts")
    calls = _names_with_kind(result, "js.call")
    assert "loadConfig" in calls
    assert "runServer" in calls


def test_extract_ts_finds_imports():
    content = (FIXTURES / "sample.ts").read_text()
    result = extract_ts(content, "src/server.ts")
    assert "loadConfig" in _names_with_kind(result, "js.import")


def test_extract_js_plain_javascript():
    content = "function foo() { return bar(); }\n"
    result = extract_js(content, "x.js")
    assert "foo" in _names_with_kind(result, "js.def")
    assert "bar" in _names_with_kind(result, "js.call")
