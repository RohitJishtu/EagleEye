"""Lazy shim — delegates to eagleeye.lineage (pandas optional for enrichment)."""

from __future__ import annotations

import importlib
from typing import Any


def __getattr__(name: str) -> Any:
    lineage = importlib.import_module("eagleeye.lineage")
    if hasattr(lineage, name):
        return getattr(lineage, name)
    from eagleeye.db_lineage import extractor as _ext

    return getattr(_ext, name)
