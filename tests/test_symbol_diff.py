"""Tests for the symbol_diff analysis module."""

from __future__ import annotations

from eagleeye.analysis.symbol_diff import (
    Signature,
    StructuralSymbolDiff,
    compute_structural_diff,
    diff_symbols,
    extract_symbols,
    format_as_markdown,
)

# ---------------------------------------------------------------------------
# Signature.to_display
# ---------------------------------------------------------------------------


def test_signature_to_display_renders_function():
    sig = Signature(
        name="greet",
        kind="function",
        params=("name",),
        return_type=None,
        decorators=(),
        is_async=False,
        bases=(),
    )
    assert sig.to_display() == "def greet(name)"


def test_signature_to_display_renders_async_with_return_type():
    sig = Signature(
        name="fetch",
        kind="function",
        params=("uid: int",),
        return_type="User",
        decorators=(),
        is_async=True,
        bases=(),
    )
    assert sig.to_display() == "async def fetch(uid: int) -> User"


def test_signature_to_display_renders_decorators():
    sig = Signature(
        name="logout",
        kind="function",
        params=(),
        return_type=None,
        decorators=("@require_auth",),
        is_async=False,
        bases=(),
    )
    assert sig.to_display() == "@require_auth\ndef logout()"


def test_signature_to_display_renders_class():
    sig = Signature(
        name="User",
        kind="class",
        params=(),
        return_type=None,
        decorators=(),
        is_async=False,
        bases=("BaseModel",),
    )
    assert sig.to_display() == "class User(BaseModel)"


# ---------------------------------------------------------------------------
# extract_symbols
# ---------------------------------------------------------------------------


def test_extract_symbols_top_level_function():
    source = "def greet(name):\n    print(name)\n"
    syms = extract_symbols("mod.py", source)
    assert len(syms) == 1
    s = syms[0]
    assert s.signature.name == "greet"
    assert s.signature.kind == "function"
    assert s.signature.params == ("name",)
    assert s.signature.is_async is False
    assert s.file == "mod.py"
    assert s.line == 1


def test_extract_symbols_method_in_class():
    source = (
        "class Greeter:\n"
        "    def say(self, name):\n"
        "        return name\n"
    )
    syms = extract_symbols("mod.py", source)
    kinds = {s.signature.name: s.signature.kind for s in syms}
    assert kinds == {"Greeter": "class", "say": "method"}


def test_extract_symbols_async_with_return_type():
    source = "async def fetch(uid: int) -> User:\n    return None\n"
    syms = extract_symbols("mod.py", source)
    assert syms[0].signature.is_async is True
    assert syms[0].signature.return_type == "User"


def test_extract_symbols_decorated_function():
    source = (
        "@require_auth\n"
        "def logout():\n"
        "    pass\n"
    )
    syms = extract_symbols("mod.py", source)
    assert syms[0].signature.decorators == ("@require_auth",)


def test_extract_symbols_body_hash_stable():
    source = "def greet(name):\n    print(name)\n"
    a = extract_symbols("mod.py", source)[0]
    b = extract_symbols("mod.py", source)[0]
    assert a.body_hash == b.body_hash


def test_extract_symbols_body_hash_changes_with_body():
    src1 = "def greet(name):\n    print(name)\n"
    src2 = "def greet(name):\n    print('hi', name)\n"
    a = extract_symbols("mod.py", src1)[0]
    b = extract_symbols("mod.py", src2)[0]
    assert a.body_hash != b.body_hash


# ---------------------------------------------------------------------------
# diff_symbols — added / removed / sig_changed / body_changed / renamed
# ---------------------------------------------------------------------------


def test_diff_detects_added_symbol():
    old = extract_symbols("m.py", "def a():\n    pass\n")
    new = extract_symbols("m.py", "def a():\n    pass\ndef b():\n    pass\n")
    changes = diff_symbols(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "added"
    assert changes[0].new.signature.name == "b"


def test_diff_detects_removed_symbol():
    old = extract_symbols("m.py", "def a():\n    pass\ndef b():\n    pass\n")
    new = extract_symbols("m.py", "def a():\n    pass\n")
    changes = diff_symbols(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "removed"
    assert changes[0].old.signature.name == "b"


def test_diff_detects_sig_changed_added_param():
    old = extract_symbols("m.py", "def f(x):\n    return x\n")
    new = extract_symbols("m.py", "def f(x, y):\n    return x\n")
    changes = diff_symbols(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "sig_changed"
    assert changes[0].old.signature.params == ("x",)
    assert changes[0].new.signature.params == ("x", "y")


def test_diff_detects_sig_changed_return_type():
    old = extract_symbols("m.py", "def f(x) -> Optional[str]:\n    return None\n")
    new = extract_symbols("m.py", "def f(x) -> str:\n    return ''\n")
    changes = diff_symbols(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "sig_changed"


def test_diff_detects_body_changed_only():
    old = extract_symbols("m.py", "def f(x):\n    return x\n")
    new = extract_symbols("m.py", "def f(x):\n    return x + 1\n")
    changes = diff_symbols(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "body_changed"


def test_diff_ignores_unchanged():
    src = "def f(x):\n    return x\n"
    old = extract_symbols("m.py", src)
    new = extract_symbols("m.py", src)
    assert diff_symbols(old, new) == []


def test_diff_detects_rename_via_body_hash():
    old = extract_symbols("m.py", "def get_user(uid):\n    return db.find(uid)\n")
    new = extract_symbols("m.py", "def fetch_user(uid):\n    return db.find(uid)\n")
    changes = diff_symbols(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "renamed"
    assert changes[0].old.signature.name == "get_user"
    assert changes[0].new.signature.name == "fetch_user"


def test_diff_does_not_rename_when_body_differs():
    old = extract_symbols("m.py", "def get_user(uid):\n    return db.find(uid)\n")
    new = extract_symbols(
        "m.py", "def fetch_user(uid):\n    return db.find_v2(uid)\n"
    )
    changes = diff_symbols(old, new)
    kinds = sorted(c.kind for c in changes)
    assert kinds == ["added", "removed"]


def test_diff_does_not_rename_across_kinds():
    # Same name reused, but kind flipped from class to function.
    old = extract_symbols("m.py", "class X:\n    pass\n")
    new = extract_symbols("m.py", "def X():\n    pass\n")
    changes = diff_symbols(old, new)
    assert not any(c.kind == "renamed" for c in changes)


# ---------------------------------------------------------------------------
# compute_structural_diff
# ---------------------------------------------------------------------------


def test_compute_structural_diff_happy_path():
    base = {"a.py": "def f(x):\n    return x\n"}
    head = {"a.py": "def f(x, y):\n    return x\n"}
    sd = compute_structural_diff(base, head)
    assert sd.files_analyzed == 1
    assert len(sd.changes) == 1
    assert sd.changes[0].kind == "sig_changed"


def test_compute_structural_diff_new_file_all_added():
    base: dict[str, str] = {}
    head = {"a.py": "def f():\n    pass\n"}
    sd = compute_structural_diff(base, head)
    assert sd.changes[0].kind == "added"


def test_compute_structural_diff_deleted_file_all_removed():
    base = {"a.py": "def f():\n    pass\n"}
    head: dict[str, str] = {}
    sd = compute_structural_diff(base, head)
    assert sd.changes[0].kind == "removed"


def test_compute_structural_diff_skips_non_python():
    base = {"a.sql": "CREATE TABLE x (id INT);"}
    head = {"a.sql": "CREATE TABLE x (id BIGINT);"}
    sd = compute_structural_diff(base, head)
    assert sd.files_skipped_non_py == 1
    assert sd.changes == []


def test_changed_names_includes_old_and_new_for_renames():
    base = {"a.py": "def old_name():\n    return 1\n"}
    head = {"a.py": "def new_name():\n    return 1\n"}
    sd = compute_structural_diff(base, head)
    names = set(sd.changed_names())
    assert names == {"old_name", "new_name"}


# ---------------------------------------------------------------------------
# format_as_markdown
# ---------------------------------------------------------------------------


def test_format_empty_diff_returns_empty_message():
    sd = StructuralSymbolDiff()
    md = format_as_markdown(sd)
    assert "## Structural Changes" in md
    assert "no symbol changes" in md.lower()


def test_format_includes_rename_section():
    base = {"a.py": "def old_name():\n    return 1\n"}
    head = {"a.py": "def new_name():\n    return 1\n"}
    sd = compute_structural_diff(base, head)
    md = format_as_markdown(sd)
    assert "Renamed" in md
    assert "old_name" in md and "new_name" in md


def test_format_hint_for_return_type_narrowing():
    base = {"a.py": "def f(x) -> Optional[str]:\n    return None\n"}
    head = {"a.py": "def f(x) -> str:\n    return ''\n"}
    sd = compute_structural_diff(base, head)
    md = format_as_markdown(sd)
    assert "narrowed" in md.lower() or "None" in md


def test_format_hint_for_async_to_sync():
    base = {"a.py": "async def fetch():\n    return 1\n"}
    head = {"a.py": "def fetch():\n    return 1\n"}
    sd = compute_structural_diff(base, head)
    md = format_as_markdown(sd)
    assert "async" in md.lower()
