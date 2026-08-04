"""Deterministic module partitioning and per-module file selection for deep evaluate."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..repo_audit import SKIP_PATH_PREFIXES, is_scannable_path

MAX_MODULES = 6
MAX_FILES_PER_MODULE = 12
MAX_MODULE_FILE_BYTES = 12000

_PREFERRED_MODULE_NAMES = frozenset({
    "core", "src", "app", "api", "server", "backend", "services", "models",
    "lib", "ingest", "agents", "jobs", "worker", "pipelines",
})

_NOISE_PREFIXES = SKIP_PATH_PREFIXES + (
    ".venv/", "venv/", "dist/", "build/", ".tox/", ".eggs/",
)

_DEFAULT_EXCLUDE_PREFIXES = ("data/", "out/", "fixtures/", "tests/", "test/", "docs/")

_ENTRYPOINT_NAMES = frozenset({
    "main.py", "app.py", "__init__.py", "__main__.py", "asgi.py", "wsgi.py",
    "index.py", "index.js", "index.ts",
})

_CONFIG_SUFFIXES = (".yml", ".yaml", ".toml", ".ini", ".cfg", ".json")


@dataclass
class ModulePlan:
    name: str
    paths: list[str] = field(default_factory=list)
    score: float = 0.0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "paths": self.paths,
            "score": self.score,
            "file_count": len(self.paths),
        }


def _should_skip_noise(path: str) -> bool:
    lower = path.lower()
    return any(lower.startswith(p) or f"/{p}" in lower for p in _NOISE_PREFIXES)


def _is_excluded_prefix(path: str, include_data_dirs: bool) -> bool:
    if include_data_dirs:
        return False
    lower = path.lower()
    return any(lower.startswith(p) for p in _DEFAULT_EXCLUDE_PREFIXES)


def _module_name_for_path(path: str, scope_prefix: str) -> str:
    """Return top-level module key relative to optional scope."""
    rel = path
    if scope_prefix and path.startswith(scope_prefix):
        rel = path[len(scope_prefix):]
    parts = rel.split("/")
    if len(parts) == 1:
        return "root"
    return parts[0]


def _score_module(name: str, paths: list[str]) -> float:
    score = float(len(paths))
    if name.lower() in _PREFERRED_MODULE_NAMES:
        score += 50.0
    if name == "root":
        score += 10.0
    return score


def _is_entrypoint(path: str) -> bool:
    return path.rsplit("/", 1)[-1].lower() in _ENTRYPOINT_NAMES


def _is_config(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(s) for s in _CONFIG_SUFFIXES) or lower.endswith("dockerfile")


def select_module_files(
    paths: list[str],
    max_files: int = MAX_FILES_PER_MODULE,
) -> list[str]:
    """Select up to max_files within a module: entrypoints, configs, then shallow source."""
    scannable = [p for p in paths if is_scannable_path(p)]
    selected: list[str] = []
    seen: set[str] = set()

    def add(candidates: list[str]) -> None:
        for p in candidates:
            if len(selected) >= max_files:
                return
            if p not in seen:
                selected.append(p)
                seen.add(p)

    entrypoints = sorted(p for p in scannable if _is_entrypoint(p))
    configs = sorted(p for p in scannable if p not in seen and _is_config(p))
    rest = sorted(
        (p for p in scannable if p not in seen),
        key=lambda p: p.count("/"),
    )

    add(entrypoints)
    if len(selected) < max_files:
        add(configs)
    if len(selected) < max_files:
        add(rest)
    return selected[:max_files]


def partition_modules(
    tree: list[dict],
    scoped_path: str | None = None,
    include_data_dirs: bool = False,
    max_modules: int = MAX_MODULES,
    max_files_per_module: int = MAX_FILES_PER_MODULE,
) -> list[ModulePlan]:
    """Partition repo tree into scored modules with per-module file selection."""
    scope_prefix = (scoped_path.rstrip("/") + "/") if scoped_path else ""

    blobs = [
        item["path"]
        for item in tree
        if item.get("type") == "blob"
        and (not scope_prefix or item["path"].startswith(scope_prefix))
    ]

    groups: dict[str, list[str]] = {}
    for path in blobs:
        if _should_skip_noise(path):
            continue
        if _is_excluded_prefix(path, include_data_dirs):
            continue
        if not is_scannable_path(path):
            continue
        name = _module_name_for_path(path, scope_prefix)
        if (
            not include_data_dirs
            and name.lower() in frozenset({"data", "out", "fixtures", "tests", "docs", "test"})
        ):
            continue
        groups.setdefault(name, []).append(path)

    plans: list[ModulePlan] = []
    for name, paths in groups.items():
        selected = select_module_files(paths, max_files=max_files_per_module)
        if not selected:
            continue
        if (
            len(selected) < 2
            and name.lower() not in _PREFERRED_MODULE_NAMES
            and name != "root"
        ):
            continue
        plans.append(
            ModulePlan(
                name=name,
                paths=selected,
                score=_score_module(name, selected),
            )
        )

    plans.sort(key=lambda m: (-m.score, m.name))
    return plans[:max_modules]
