"""Tests for features/pr_review helpers."""
import os
from unittest.mock import patch

from eagleeye.features.pr_review import _save_review
from eagleeye.models import PRReviewResult


def _make_result():
    return PRReviewResult(summary="s", overall_verdict="approve", risk_level="low")


def test_save_review_uses_eagleeye_reviews_dir(tmp_path):
    custom_dir = tmp_path / "custom_reviews"
    env = {"EAGLEEYE_REVIEWS_DIR": str(custom_dir)}
    with patch.dict(os.environ, env, clear=False):
        path = _save_review("owner", "repo", 1, "My PR title", _make_result())
    assert str(custom_dir) in str(path)
    assert path.exists()


def test_save_review_defaults_to_reviews_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.environ.pop("EAGLEEYE_REVIEWS_DIR", None)
    path = _save_review("owner", "repo", 1, "My PR title", _make_result())
    assert "reviews" in str(path)
    assert path.exists()
