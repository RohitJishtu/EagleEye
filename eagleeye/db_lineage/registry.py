"""Provider registry — the ONE file to change when adding a new database.

To add BigQuery support:
1. Create eagleeye/db_lineage/bigquery.py with BigQueryLineageProvider(DBLineageProvider)
2. Add  "bigquery": BigQueryLineageProvider  to _PROVIDERS below
That is it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .provider import DBLineageProvider

_PROVIDERS: dict[str, type] = {}
_defaults_loaded = False


def get_provider(name: str) -> "DBLineageProvider":
    _load_defaults()
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(
            f"Unknown lineage provider: {name!r}. Available: {sorted(_PROVIDERS)}"
        )
    return cls()


def _register(name: str, cls: type) -> None:
    _PROVIDERS[name] = cls


def _load_defaults() -> None:
    global _defaults_loaded
    if _defaults_loaded:
        return
    from . import snowflake_metadata  # noqa: F401 — triggers _register("snowflake", ...)

    _defaults_loaded = True
