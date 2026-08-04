"""RepoMap persistence — lightweight repo profiles at ~/.eagleeye/maps/."""

from __future__ import annotations

import json
from pathlib import Path

from ..core.models import RepoMap

_MAPS_DIR = Path.home() / ".eagleeye" / "maps"


def maps_dir() -> Path:
    return _MAPS_DIR


def map_path(owner: str, repo: str) -> Path:
    return _MAPS_DIR / f"{owner}__{repo}.json"


def save_map(repo_map: RepoMap) -> Path:
    _MAPS_DIR.mkdir(parents=True, exist_ok=True)
    path = map_path(repo_map.owner, repo_map.repo)
    path.write_text(repo_map.model_dump_json(indent=2))
    return path


def load_map(owner: str, repo: str) -> RepoMap | None:
    path = map_path(owner, repo)
    if not path.exists():
        return None
    try:
        return RepoMap.model_validate_json(path.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def list_maps() -> list[RepoMap]:
    if not _MAPS_DIR.exists():
        return []
    maps: list[RepoMap] = []
    for path in sorted(_MAPS_DIR.glob("*.json")):
        try:
            maps.append(RepoMap.model_validate_json(path.read_text()))
        except (json.JSONDecodeError, ValueError):
            continue
    return maps
