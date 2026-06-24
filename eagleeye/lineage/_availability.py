"""Optional dependency checks for database lineage features."""

from __future__ import annotations

INSTALL_HINT = "Install optional lineage support: pip install 'eagleeye[lineage]'"

_MISSING: tuple[str, ...] | None = None
_MISSING_REFRESH: tuple[str, ...] | None = None


def _check_import(module: str, package_name: str, missing: list[str]) -> None:
    try:
        __import__(module)
    except ImportError:
        missing.append(package_name)


def missing_dependencies() -> tuple[str, ...]:
    """Packages required for snapshot enrichment (pandas-backed resolvers)."""
    global _MISSING
    if _MISSING is None:
        missing: list[str] = []
        _check_import("pandas", "pandas", missing)
        _MISSING = tuple(missing)
    return _MISSING


def missing_refresh_dependencies() -> tuple[str, ...]:
    """Packages required for live Snowflake snapshot refresh."""
    global _MISSING_REFRESH
    if _MISSING_REFRESH is None:
        missing = list(missing_dependencies())
        _check_import("snowflake.connector", "snowflake-connector-python", missing)
        _MISSING_REFRESH = tuple(missing)
    return _MISSING_REFRESH


def is_available() -> bool:
    """True when pandas is installed (snapshot enrichment / DB resolvers)."""
    return not missing_dependencies()


def require_lineage(*, feature: str = "lineage") -> None:
    """Raise ImportError with install hint when lineage extras are missing."""
    missing = missing_dependencies()
    if missing:
        raise ImportError(
            f"EagleEye {feature} requires: {', '.join(missing)}. {INSTALL_HINT}"
        )


def require_lineage_refresh(*, feature: str = "lineage refresh") -> None:
    """Raise ImportError when refresh-specific deps are missing."""
    missing = missing_refresh_dependencies()
    if missing:
        raise ImportError(
            f"EagleEye {feature} requires: {', '.join(missing)}. {INSTALL_HINT}"
        )
