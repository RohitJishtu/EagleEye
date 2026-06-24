"""Centralized path helpers for EagleEye data directories."""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_REVIEWS_ROOT = _PACKAGE_ROOT / "reviews"


def eagleeye_home() -> Path:
    """Return EagleEye's user data directory (~/.eagleeye or EAGLEEYE_HOME)."""
    return Path(os.environ.get("EAGLEEYE_HOME", Path.home() / ".eagleeye"))


def reviews_root() -> Path:
    """Return the root directory for saved PR reviews."""
    return Path(os.environ.get("EAGLEEYE_REVIEWS_DIR", _DEFAULT_REVIEWS_ROOT))


def reviews_dir(owner: str, repo: str) -> Path:
    """Return the reviews directory for a specific repository."""
    return reviews_root() / f"{owner}-{repo}"
