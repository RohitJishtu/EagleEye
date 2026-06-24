"""Keyword filters for deciding which specialist agents run."""

from __future__ import annotations

_SCHEMA_KEYWORDS = (
    ".sql", ".ddl", ".hql",
    "migration", "alembic",
    "schema", "model.py", "models.py",
    "pydantic", "serializer", "dto", "typedef",
    "types.py", "table.py", "tables.py", "entities.py",
)
_PIPELINE_KEYWORDS = (".yml", ".yaml", "dag", "airflow", "dbt", "pipeline", "workflow", "spark", "databricks")
_FEATURE_KEYWORDS = ("feature", "featuregroup", "feature_group", "feature_store", "training", "inference")
_ARCH_KEYWORDS = (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb", ".cs")


def _has_relevant_files(file_list: list[str], keywords: tuple[str, ...]) -> bool:
    return any(kw in f.lower() for f in file_list for kw in keywords)
