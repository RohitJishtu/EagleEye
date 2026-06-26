from pathlib import Path

from eagleeye.reference_store import extract_py

FIXTURES = Path(__file__).parent / "fixtures"


def _names_with_kind(result, kind):
    return [name for name, m in result if m.kind == kind]


def test_extract_py_finds_function_def():
    content = (FIXTURES / "sample.py").read_text()
    result = extract_py(content, "sample.py")
    assert "run_job" in _names_with_kind(result, "py.def")


def test_extract_py_finds_class_def():
    content = (FIXTURES / "sample.py").read_text()
    result = extract_py(content, "sample.py")
    assert "Job" in _names_with_kind(result, "py.def")


def test_extract_py_finds_method_def():
    content = (FIXTURES / "sample.py").read_text()
    result = extract_py(content, "sample.py")
    assert "execute" in _names_with_kind(result, "py.def")


def test_extract_py_finds_calls():
    content = (FIXTURES / "sample.py").read_text()
    result = extract_py(content, "sample.py")
    calls = _names_with_kind(result, "py.call")
    assert "build_config" in calls
    assert "load_pipeline" in calls
    assert "run_job" in calls


def test_extract_py_finds_imports():
    content = (FIXTURES / "sample.py").read_text()
    result = extract_py(content, "sample.py")
    assert "load_pipeline" in _names_with_kind(result, "py.import")


def test_extract_py_skips_string_literals():
    content = (FIXTURES / "sample.py").read_text()
    result = extract_py(content, "sample.py")
    assert "fake_function" not in [name for name, _ in result]


def test_extract_py_snippet_includes_signature():
    content = (FIXTURES / "sample.py").read_text()
    result = extract_py(content, "sample.py")
    run_job_def = next(m for name, m in result if name == "run_job" and m.kind == "py.def")
    assert "def run_job" in run_job_def.snippet


def test_extract_py_pure_function_no_io(tmp_path, monkeypatch):
    """Extractor must not read from disk or env."""
    monkeypatch.chdir(tmp_path)
    extract_py("def x(): pass\n", "x.py")
