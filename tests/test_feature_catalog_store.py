import time
import pytest
from eagleeye.feature_catalog_store import (
    FeatureCatalog,
    FeatureCatalogEntry,
    FeatureConsumerEntry,
    save_catalog,
    load_catalog,
    list_catalogs,
    get_catalogs_for_org,
    build_catalog,
    refresh_catalog,
    add_consumers_from_review,
    get_matching_features,
    format_lineage_prompt,
    is_stale,
)


@pytest.fixture
def tmp_catalog_dir(tmp_path, monkeypatch):
    catalogs_dir = tmp_path / "catalogs"
    catalogs_dir.mkdir()
    import eagleeye.feature_catalog_store as m
    monkeypatch.setattr(m, "_CATALOGS_DIR", catalogs_dir)
    return catalogs_dir


def _make_catalog() -> FeatureCatalog:
    now = time.time()
    return FeatureCatalog(
        feature_store_repo="org/feature-store",
        built_at=now,
        refreshed_at=now,
        features={
            "acct_score": FeatureCatalogEntry(
                feature_name="acct_score",
                feature_group="account_features",
                feature_type="float",
                source_file="src/account_features.py",
                load_jobs=["load_account_features_monthly"],
                consumers=[
                    FeatureConsumerEntry(
                        repo="org/ml-repo",
                        file="train_model.py",
                        line=42,
                        role="training",
                        snippet="acct_score = features['acct_score']",
                    )
                ],
            )
        },
    )


def test_save_and_load_catalog(tmp_catalog_dir):
    catalog = _make_catalog()
    path = save_catalog(catalog)
    assert path.exists()
    loaded = load_catalog("org", "feature-store")
    assert loaded is not None
    assert loaded.feature_store_repo == "org/feature-store"
    assert "acct_score" in loaded.features
    entry = loaded.features["acct_score"]
    assert entry.feature_type == "float"
    assert len(entry.consumers) == 1
    assert entry.consumers[0].repo == "org/ml-repo"


def test_load_catalog_missing_returns_none(tmp_catalog_dir):
    result = load_catalog("org", "nonexistent")
    assert result is None


def test_list_catalogs(tmp_catalog_dir):
    save_catalog(_make_catalog())
    catalogs = list_catalogs()
    assert len(catalogs) == 1
    assert catalogs[0].feature_store_repo == "org/feature-store"


def test_get_catalogs_for_org(tmp_catalog_dir):
    save_catalog(_make_catalog())
    # Catalog for different org should not appear
    other = _make_catalog()
    other.feature_store_repo = "other-org/feature-store"
    save_catalog(other)
    results = get_catalogs_for_org("org")
    assert len(results) == 1
    assert results[0].feature_store_repo == "org/feature-store"


# ---------------------------------------------------------------------------
# build_catalog / refresh_catalog tests
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock


def test_build_catalog_extracts_features(tmp_catalog_dir):
    github = MagicMock()
    github.get_feature_store_files.return_value = {
        "src/account_features.py": (
            "acct_score = FloatType()\n"
            "acct_propensity = FloatType()\n"
        ),
        "jobs/load_account_features.yml": (
            "name: load_account_features_monthly\n"
            "feature_group: account_features\n"
        ),
    }
    catalog = build_catalog("org", "feature-store", github)
    assert catalog.feature_store_repo == "org/feature-store"
    assert catalog.built_at > 0


def test_build_catalog_saves_to_disk(tmp_catalog_dir):
    github = MagicMock()
    github.get_feature_store_files.return_value = {
        "src/account_features.py": "acct_score = FloatType()\n",
    }
    catalog = build_catalog("org", "feature-store", github)
    save_catalog(catalog)
    loaded = load_catalog("org", "feature-store")
    assert loaded is not None
    assert loaded.feature_store_repo == "org/feature-store"


def test_refresh_catalog_preserves_consumers(tmp_catalog_dir):
    catalog = _make_catalog()  # has acct_score with 1 consumer
    save_catalog(catalog)

    github = MagicMock()
    github.get_feature_store_files.return_value = {
        "src/account_features.py": "acct_score = FloatType()\n",
    }
    refreshed = refresh_catalog("org", "feature-store", github)
    # Consumer from original catalog should be preserved
    assert "acct_score" in refreshed.features
    assert len(refreshed.features["acct_score"].consumers) >= 1


# ---------------------------------------------------------------------------
# add_consumers_from_review / get_matching_features / format_lineage_prompt / is_stale
# ---------------------------------------------------------------------------


def test_add_consumers_from_review_registers_new_consumer(tmp_catalog_dir):
    catalog = _make_catalog()
    save_catalog(catalog)
    diff = "+acct_score = features['acct_score']"
    file_contents = {"train_other.py": "acct_score = features['acct_score']"}
    add_consumers_from_review("org", "feature-store", "org/other-repo", diff, file_contents)
    updated = load_catalog("org", "feature-store")
    assert updated is not None
    repos = [c.repo for c in updated.features["acct_score"].consumers]
    assert "org/other-repo" in repos


def test_add_consumers_from_review_no_duplicate(tmp_catalog_dir):
    catalog = _make_catalog()
    save_catalog(catalog)
    diff = "+acct_score = features['acct_score']"
    file_contents = {"train_model.py": "acct_score = features['acct_score']"}
    add_consumers_from_review("org", "feature-store", "org/ml-repo", diff, file_contents)
    after_first = load_catalog("org", "feature-store")
    count_after_first = len([
        c for c in after_first.features["acct_score"].consumers
        if c.repo == "org/ml-repo" and c.file == "train_model.py"
    ])
    # Calling a second time with the same inputs must not add any new entries
    add_consumers_from_review("org", "feature-store", "org/ml-repo", diff, file_contents)
    updated = load_catalog("org", "feature-store")
    ml_consumers = [
        c for c in updated.features["acct_score"].consumers
        if c.repo == "org/ml-repo" and c.file == "train_model.py"
    ]
    assert len(ml_consumers) == count_after_first


def test_get_matching_features_explicit_name(tmp_catalog_dir):
    catalog = _make_catalog()
    diff = "+result = model.predict(acct_score)"
    matches = get_matching_features(catalog, diff, {})
    assert any(e.feature_name == "acct_score" for e in matches)


def test_get_matching_features_implicit_file(tmp_catalog_dir):
    catalog = _make_catalog()
    # train_model.py is a known consumer of acct_score (from _make_catalog fixture)
    diff = "+++ b/train_model.py\n+some_change = True"
    matches = get_matching_features(catalog, diff, {})
    assert any(e.feature_name == "acct_score" for e in matches)


def test_get_matching_features_no_match(tmp_catalog_dir):
    catalog = _make_catalog()
    diff = "+++ b/ci_config.yml\n+timeout: 30"
    matches = get_matching_features(catalog, diff, {})
    assert matches == []


def test_format_lineage_prompt_consumer_direction(tmp_catalog_dir):
    catalog = _make_catalog()
    entries = list(catalog.features.values())
    prompt = format_lineage_prompt(entries, reviewing_feature_store=False)
    assert "acct_score" in prompt
    assert "org/ml-repo" in prompt
    assert "Feature Store Lineage" in prompt


def test_format_lineage_prompt_feature_store_direction(tmp_catalog_dir):
    catalog = _make_catalog()
    entries = list(catalog.features.values())
    prompt = format_lineage_prompt(entries, reviewing_feature_store=True)
    assert "may break" in prompt


def test_is_stale_fresh_catalog(tmp_catalog_dir):
    catalog = _make_catalog()
    assert not is_stale(catalog)


def test_is_stale_old_catalog(tmp_catalog_dir):
    catalog = _make_catalog()
    catalog.refreshed_at = time.time() - (8 * 86400)  # 8 days ago
    assert is_stale(catalog)
