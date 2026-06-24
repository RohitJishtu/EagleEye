"""Feature catalog store — save and retrieve feature store catalogs.

Catalogs live at ~/.eagleeye/catalogs/{owner}__{repo}.json

Usage:
  save_catalog(catalog)               # persist a FeatureCatalog
  load_catalog(owner, repo)           # retrieve by owner/repo
  list_catalogs()                     # list all saved catalogs
  get_catalogs_for_org(owner)         # catalogs belonging to a given org
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

_CATALOGS_DIR = Path.home() / ".eagleeye" / "catalogs"



@dataclass
class FeatureConsumerEntry:
    repo: str       # "owner/repo" of the consuming repo
    file: str       # file path in consumer repo
    line: int
    role: str       # training | inference | load | register | validation | other
    snippet: str    # line of code, truncated to 100 chars


@dataclass
class FeatureCatalogEntry:
    feature_name: str
    feature_group: str
    feature_type: str   # float | Optional[float] | int | str etc.
    source_file: str    # path in feature store repo
    load_jobs: list[str] = field(default_factory=list)
    consumers: list[FeatureConsumerEntry] = field(default_factory=list)


@dataclass
class FeatureCatalog:
    feature_store_repo: str   # "owner/repo"
    built_at: float           # Unix timestamp
    refreshed_at: float
    features: dict[str, FeatureCatalogEntry] = field(default_factory=dict)



def _ensure_dir() -> None:
    _CATALOGS_DIR.mkdir(parents=True, exist_ok=True)


def _catalog_path(owner: str, repo: str) -> Path:
    return _CATALOGS_DIR / f"{owner}__{repo}.json"


def _serialize_catalog(catalog: FeatureCatalog) -> dict:
    """Serialize a FeatureCatalog to a JSON-safe dict."""
    data = {
        "feature_store_repo": catalog.feature_store_repo,
        "built_at": catalog.built_at,
        "refreshed_at": catalog.refreshed_at,
        "features": {
            name: {
                **{k: v for k, v in asdict(entry).items() if k != "consumers"},
                "consumers": [asdict(c) for c in entry.consumers],
            }
            for name, entry in catalog.features.items()
        },
    }
    return data


def _deserialize_catalog(data: dict) -> FeatureCatalog:
    """Reconstruct a FeatureCatalog from a JSON dict."""
    features: dict[str, FeatureCatalogEntry] = {}
    for name, entry_data in data.get("features", {}).items():
        consumers = [
            FeatureConsumerEntry(**c) for c in entry_data.get("consumers", [])
        ]
        entry_fields = {k: v for k, v in entry_data.items() if k != "consumers"}
        features[name] = FeatureCatalogEntry(**entry_fields, consumers=consumers)

    return FeatureCatalog(
        feature_store_repo=data["feature_store_repo"],
        built_at=data["built_at"],
        refreshed_at=data["refreshed_at"],
        features=features,
    )



def save_catalog(catalog: FeatureCatalog) -> Path:
    """Persist a FeatureCatalog to disk. Returns the file path written."""
    _ensure_dir()
    owner, repo = catalog.feature_store_repo.split("/", 1)
    path = _catalog_path(owner, repo)
    path.write_text(json.dumps(_serialize_catalog(catalog), indent=2))
    return path


def load_catalog(owner: str, repo: str) -> Optional[FeatureCatalog]:
    """Load a catalog by owner and repo. Returns None if not found or corrupt."""
    path = _catalog_path(owner, repo)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return _deserialize_catalog(data)
    except (json.JSONDecodeError, TypeError, KeyError, OSError):
        return None


def list_catalogs() -> list[FeatureCatalog]:
    """Return all saved catalogs."""
    if not _CATALOGS_DIR.exists():
        return []
    catalogs = []
    for p in sorted(_CATALOGS_DIR.glob("*__*.json")):
        try:
            data = json.loads(p.read_text())
            catalogs.append(_deserialize_catalog(data))
        except (json.JSONDecodeError, TypeError, KeyError, OSError):
            pass
    return catalogs


def get_catalogs_for_org(owner: str) -> list[FeatureCatalog]:
    """Return all catalogs where feature_store_repo starts with 'owner/'."""
    prefix = f"{owner}/"
    return [c for c in list_catalogs() if c.feature_store_repo.startswith(prefix)]



def _make_pseudo_diff(file_contents: dict[str, str]) -> str:
    """Wrap full file contents as a pseudo-diff (all lines as additions)."""
    lines = []
    for path, content in file_contents.items():
        lines.append(f"diff --git a/{path} b/{path}")
        lines.append(f"+++ b/{path}")
        lines.append("@@ -0,0 +1,9999 @@")
        for line in content.splitlines():
            lines.append(f"+{line}")
    return "\n".join(lines)


def _infer_feature_group(file_path: str) -> str:
    """Infer feature group from file stem."""
    stem = Path(file_path).stem
    return stem.replace("_features", "").replace("_feature", "")


def _extract_to_catalog_entries(
    extract, file_contents: dict[str, str]
) -> dict[str, FeatureCatalogEntry]:
    """Convert a FeatureStoreExtract into FeatureCatalogEntry objects."""
    entries: dict[str, FeatureCatalogEntry] = {}

    for col in extract.column_changes:
        if not col.column_name or len(col.column_name) < 3:
            continue
        entries[col.column_name] = FeatureCatalogEntry(
            feature_name=col.column_name,
            feature_group=_infer_feature_group(col.file),
            feature_type=col.new_type or col.old_type or "",
            source_file=col.file,
        )

    # Map load jobs onto features by feature group match
    for job in extract.job_changes:
        for group in job.feature_groups:
            for entry in entries.values():
                if entry.feature_group == group or group in entry.source_file:
                    if job.job_name not in entry.load_jobs:
                        entry.load_jobs.append(job.job_name)

    # Map consumers found within the feature store repo itself
    for feature_name, hits in extract.consumers.items():
        if feature_name not in entries:
            continue
        for hit in hits:
            entries[feature_name].consumers.append(
                FeatureConsumerEntry(
                    repo="",  # within same repo — repo filled by caller
                    file=hit.file,
                    line=hit.line,
                    role=hit.consumer_kind or "other",
                    snippet=hit.snippet[:100],
                )
            )

    return entries


def build_catalog(owner: str, repo: str, github) -> FeatureCatalog:
    """Build a FeatureCatalog by fetching and analysing the feature store repo."""
    from eagleeye.analysis.feature_store import compute_feature_store_extract

    file_contents = github.get_feature_store_files(owner, repo)
    pseudo_diff = _make_pseudo_diff(file_contents)
    extract = compute_feature_store_extract(pseudo_diff, file_contents)
    features = _extract_to_catalog_entries(extract, file_contents)

    now = time.time()
    return FeatureCatalog(
        feature_store_repo=f"{owner}/{repo}",
        built_at=now,
        refreshed_at=now,
        features=features,
    )


def refresh_catalog(owner: str, repo: str, github) -> FeatureCatalog:
    """Re-fetch the feature store repo and merge into the existing catalog (preserves consumers)."""
    existing = load_catalog(owner, repo)
    fresh = build_catalog(owner, repo, github)

    if existing:
        for name, old_entry in existing.features.items():
            if name in fresh.features:
                known = {(c.repo, c.file, c.line) for c in fresh.features[name].consumers}
                for c in old_entry.consumers:
                    if (c.repo, c.file, c.line) not in known:
                        fresh.features[name].consumers.append(c)
            else:
                fresh.features[name] = old_entry
        fresh.built_at = existing.built_at

    save_catalog(fresh)
    return fresh



def add_consumers_from_review(
    owner: str,
    repo: str,
    reviewing_repo: str,
    diff: str,
    file_contents: dict[str, str],
) -> None:
    """Register consumer entries found in a reviewed PR into the catalog."""
    catalog = load_catalog(owner, repo)
    if not catalog or not catalog.features:
        return

    from eagleeye.analysis.feature_store import _find_feature_consumers, _classify_file

    feature_names = list(catalog.features.keys())
    found = _find_feature_consumers(feature_names, [], file_contents)

    changed = False
    for feature_name, hits in found.items():
        if feature_name not in catalog.features:
            continue
        entry = catalog.features[feature_name]
        existing_keys = {(c.repo, c.file, c.line) for c in entry.consumers}
        for hit in hits:
            key = (reviewing_repo, hit.file, hit.line)
            if key not in existing_keys:
                entry.consumers.append(FeatureConsumerEntry(
                    repo=reviewing_repo,
                    file=hit.file,
                    line=hit.line,
                    role=hit.consumer_kind or _classify_file(hit.file),
                    snippet=hit.snippet[:100],
                ))
                existing_keys.add(key)
                changed = True

    if changed:
        save_catalog(catalog)


def get_matching_features(
    catalog: FeatureCatalog,
    diff: str,
    file_contents: dict[str, str],
) -> list[FeatureCatalogEntry]:
    """Return catalog entries matched by explicit name in diff OR implicit consumer file match."""
    import re
    matched: dict[str, FeatureCatalogEntry] = {}

    # Explicit: feature name literally in the diff
    for name, entry in catalog.features.items():
        if re.search(r'\b' + re.escape(name) + r'\b', diff, re.IGNORECASE):
            matched[name] = entry

    # Implicit: a changed file is a known consumer file
    changed_files: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            changed_files.add(line[6:])

    for name, entry in catalog.features.items():
        if name in matched:
            continue
        for consumer in entry.consumers:
            if consumer.file in changed_files:
                matched[name] = entry
                break

    return list(matched.values())


def format_lineage_prompt(
    entries: list[FeatureCatalogEntry],
    reviewing_feature_store: bool = False,
) -> str:
    """Format matched feature entries as a markdown section for Claude."""
    if not entries:
        return ""

    lines = ["## Feature Store Lineage — Cross-Repo Impact\n"]

    for entry in entries[:10]:
        consumers = entry.consumers
        repos = {c.repo for c in consumers if c.repo}
        type_info = f" · type: {entry.feature_type}" if entry.feature_type else ""

        lines.append(f"⚠️  **`{entry.feature_name}`**  [group: {entry.feature_group}{type_info}]")
        lines.append(f"   Defined in: `{entry.source_file}`")

        if entry.load_jobs:
            lines.append(f"   Load job(s): {', '.join(entry.load_jobs)}")

        if consumers:
            lines.append(f"   Consumers ({len(consumers)} across {len(repos)} repo(s)):")
            for c in consumers[:6]:
                loc = f"{c.repo} / {c.file}:{c.line}" if c.repo else f"{c.file}:{c.line}"
                lines.append(f"     [{c.role}]  {loc}")
            if len(consumers) > 6:
                lines.append(f"     ... and {len(consumers) - 6} more")
        else:
            lines.append("   No registered consumers yet.")

        if reviewing_feature_store and consumers:
            lines.append(
                f"   ⚡ Changing this feature may break {len(consumers)} "
                f"consumer(s) across {len(repos)} repo(s)."
            )
        lines.append("")

    return "\n".join(lines)


def is_stale(catalog: FeatureCatalog, days: int = 7) -> bool:
    """Return True if the catalog was last refreshed more than `days` days ago."""
    return (time.time() - catalog.refreshed_at) > (days * 86400)
