"""Redact secrets before sending content to LLM or saving reports."""

from __future__ import annotations

import re

_SECRET_PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "ghp_****"),
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "sk-ant-****"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA****"),
    (re.compile(r"(?i)(password|secret|token|api_key)\s*=\s*['\"][^'\"]{6,}['\"]"), r"\1=****"),
]


def redact_text(text: str) -> str:
    out = text
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_file_contents(contents: dict[str, str]) -> dict[str, str]:
    return {path: redact_text(content) for path, content in contents.items()}
