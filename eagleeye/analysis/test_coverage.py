"""Test coverage analysis: check if the repo has tests and whether changed code is covered.

Detects:
  - Whether a test suite exists (test files, test directories, pytest/unittest config)
  - Which changed files have corresponding test files
  - Which changed functions/classes have no matching test
  - Data-level test patterns (fixtures, factories, test data files)
  - Missing tests for changed schema elements (models, SQL, API handlers)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath



@dataclass
class TestFile:
    path: str
    framework: str   # "pytest" | "unittest" | "jest" | "unknown"
    has_data_fixtures: bool = False


@dataclass
class UncoveredChange:
    changed_file: str
    symbol: str          # function/class/method name
    reason: str          # why we think it's uncovered


@dataclass
class TestCoverageResult:
    has_tests: bool = False
    test_files: list[TestFile] = field(default_factory=list)
    test_frameworks: list[str] = field(default_factory=list)
    has_data_fixtures: bool = False
    fixture_files: list[str] = field(default_factory=list)
    changed_files_with_tests: list[str] = field(default_factory=list)
    changed_files_without_tests: list[str] = field(default_factory=list)
    uncovered_changes: list[UncoveredChange] = field(default_factory=list)
    config_files_found: list[str] = field(default_factory=list)


# Test file naming conventions
_TEST_FILE_RE = re.compile(
    r"(^|/)test[_\-]|[_\-]test\.(py|js|ts|java|go|rb|rs)$|"
    r"(^|/)spec[_\-]|[_\-]spec\.(py|js|ts)$|"
    r"\.test\.(js|ts|jsx|tsx)$|"
    r"\.spec\.(js|ts|jsx|tsx)$",
    re.IGNORECASE,
)

_TEST_DIR_RE = re.compile(r"(^|/)tests?/|/__tests__/|/spec/", re.IGNORECASE)

# Test framework signals in file content
_PYTEST_RE = re.compile(r"import pytest|@pytest\.|def test_|from pytest")
_UNITTEST_RE = re.compile(r"import unittest|unittest\.TestCase|self\.assert")
_JEST_RE = re.compile(r"describe\(|it\(|expect\(|jest\.")
_MOCHA_RE = re.compile(r"describe\(|it\(|chai\.|mocha")

# Data fixture patterns
_FIXTURE_RE = re.compile(
    r"@pytest\.fixture|factory_boy|faker|FactoryBoy|"
    r"fixtures/|testdata/|test_data/|conftest\.py|"
    r"\.fixture\.(json|yaml|yml|csv|sql)$|"
    r"fixtures\.py|factories\.py|seeds\.py|seed_data",
    re.IGNORECASE,
)

# Test config files
_TEST_CONFIG_FILES = {
    "pytest.ini", "setup.cfg", "pyproject.toml", "tox.ini",
    "jest.config.js", "jest.config.ts", ".mocharc.js", ".mocharc.yml",
    "phpunit.xml", "karma.conf.js",
}

# Symbols we care about testing
_FUNC_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
_CLASS_DEF_RE = re.compile(r"^class\s+(\w+)", re.MULTILINE)



def _detect_framework(content: str) -> str:
    if _PYTEST_RE.search(content):
        return "pytest"
    if _UNITTEST_RE.search(content):
        return "unittest"
    if _JEST_RE.search(content):
        return "jest"
    if _MOCHA_RE.search(content):
        return "mocha"
    return "unknown"


def _is_test_file(path: str) -> bool:
    return bool(_TEST_FILE_RE.search(path) or _TEST_DIR_RE.search(path))


def _has_data_fixtures(path: str, content: str) -> bool:
    return bool(_FIXTURE_RE.search(path) or _FIXTURE_RE.search(content[:2000]))


def _source_to_test_candidates(source_path: str) -> list[str]:
    """Generate candidate test file paths for a source file."""
    p = PurePosixPath(source_path)
    stem = p.stem
    candidates = [
        str(p.parent / f"test_{stem}{p.suffix}"),
        str(p.parent / f"{stem}_test{p.suffix}"),
        f"tests/test_{stem}{p.suffix}",
        f"tests/{stem}_test{p.suffix}",
        f"test/test_{stem}{p.suffix}",
        f"__tests__/{stem}.test{p.suffix}",
        f"__tests__/{stem}.spec{p.suffix}",
    ]
    return candidates


def _extract_changed_symbols(diff: str, path: str) -> list[str]:
    """Extract function/class names touched by the diff for a given file."""
    symbols = []
    in_file = False
    current_file = ""

    for line in diff.splitlines():
        if line.startswith("diff --git"):
            current_file = line.split(" b/")[-1] if " b/" in line else ""
            in_file = (current_file == path)
            continue
        if not in_file:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            m = _FUNC_DEF_RE.match(content)
            if m:
                name = m.group(1)
                if not name.startswith("test_"):
                    symbols.append(name)
            m = _CLASS_DEF_RE.match(content)
            if m:
                symbols.append(m.group(1))

    return list(dict.fromkeys(symbols))  # deduplicate, preserve order


def _symbol_has_test(symbol: str, file_contents: dict[str, str]) -> bool:
    """Check if any test file references this symbol name."""
    pattern = re.compile(r'\b' + re.escape(symbol) + r'\b')
    for path, content in file_contents.items():
        if _is_test_file(path) and pattern.search(content):
            return True
    return False



def compute_test_coverage(diff: str, file_contents: dict[str, str], file_list: list[str]) -> TestCoverageResult:
    """Analyze test coverage for a PR.

    Args:
        diff: raw unified diff
        file_contents: {path: content} for files fetched from the repo
        file_list: all files changed in the PR
    """
    result = TestCoverageResult()

    # Scan for test files and config files
    for path, content in file_contents.items():
        fname = PurePosixPath(path).name
        if fname in _TEST_CONFIG_FILES:
            result.config_files_found.append(path)

        if _is_test_file(path):
            result.has_tests = True
            framework = _detect_framework(content)
            has_fixtures = _has_data_fixtures(path, content)
            result.test_files.append(TestFile(path=path, framework=framework, has_data_fixtures=has_fixtures))
            if has_fixtures:
                result.has_data_fixtures = True
                result.fixture_files.append(path)

        # Also check for fixture/factory files not in test directories
        if _has_data_fixtures(path, content) and not _is_test_file(path):
            if "fixture" in path.lower() or "factory" in path.lower() or "conftest" in path.lower():
                result.has_data_fixtures = True
                result.fixture_files.append(path)

    result.test_frameworks = list({tf.framework for tf in result.test_files if tf.framework != "unknown"})

    # For each changed source file, check if a test file exists
    source_files = [f for f in file_list if not _is_test_file(f)]
    all_paths = set(file_contents.keys())

    for source in source_files:
        candidates = _source_to_test_candidates(source)
        has_test = any(c in all_paths for c in candidates)

        # Also check if any test file in file_contents imports or references this module
        if not has_test:
            module_name = PurePosixPath(source).stem
            pattern = re.compile(r'\b' + re.escape(module_name) + r'\b')
            for path, content in file_contents.items():
                if _is_test_file(path) and pattern.search(content):
                    has_test = True
                    break

        if has_test:
            result.changed_files_with_tests.append(source)
        else:
            result.changed_files_without_tests.append(source)

        # Check which specific changed symbols have no test coverage
        if result.has_tests:
            for symbol in _extract_changed_symbols(diff, source):
                if not _symbol_has_test(symbol, file_contents):
                    result.uncovered_changes.append(UncoveredChange(
                        changed_file=source,
                        symbol=symbol,
                        reason=f"No test references `{symbol}` in any test file",
                    ))

    return result



def format_as_markdown(result: TestCoverageResult) -> str:
    lines = ["## Test Coverage Analysis", ""]

    if not result.has_tests:
        lines += [
            "⚠️ **No test files detected in the fetched files.**",
            "",
            "This repo appears to have no automated test suite, or tests are in a directory "
            "not included in this PR's file set. Changes are shipping without test verification.",
            "",
        ]
        if result.config_files_found:
            lines.append(f"_Test config found ({', '.join(result.config_files_found)}) "
                         "but no test files were fetched — tests may exist elsewhere._")
        return "\n".join(lines)

    # Frameworks and fixtures
    fw = ", ".join(result.test_frameworks) if result.test_frameworks else "unknown"
    lines.append(f"**Frameworks detected:** {fw}")
    if result.has_data_fixtures:
        lines.append(f"**Data fixtures/factories:** ✓ ({len(result.fixture_files)} file(s))")
    else:
        lines.append("**Data fixtures/factories:** ✗ none detected")
    lines.append(f"**Test files in context:** {len(result.test_files)}")
    lines.append("")

    # Coverage by changed file
    lines += ["### Changed Files — Test Coverage", ""]
    if result.changed_files_with_tests:
        lines.append("**Covered (test file found):**")
        for f in result.changed_files_with_tests:
            lines.append(f"  - ✅ `{f}`")
        lines.append("")

    if result.changed_files_without_tests:
        lines.append("**Not covered (no test file found):**")
        for f in result.changed_files_without_tests:
            lines.append(f"  - ❌ `{f}`")
        lines.append("")

    # Uncovered symbols
    if result.uncovered_changes:
        lines += ["### Changed Symbols Without Test Coverage", ""]
        lines.append("The following functions/classes were added or modified but have no test referencing them:")
        lines.append("")
        lines.append("| Symbol | File | Reason |")
        lines.append("|---|---|---|")
        for u in result.uncovered_changes[:20]:
            lines.append(f"| `{u.symbol}` | `{u.changed_file}` | {u.reason} |")
        if len(result.uncovered_changes) > 20:
            lines.append(f"| _…and {len(result.uncovered_changes) - 20} more_ | | |")
        lines.append("")
        lines.append(
            "⚠️ **Review checklist:** each uncovered symbol above is a risk — "
            "if the change introduces a bug, there is no automated safety net."
        )
    else:
        lines += [
            "### Uncovered Changes",
            "",
            "✅ All detected changed symbols appear to have test coverage.",
        ]

    return "\n".join(lines)
