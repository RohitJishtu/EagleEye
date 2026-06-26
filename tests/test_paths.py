"""Tests for eagleeye.core.paths."""

import os
from pathlib import Path
from unittest.mock import patch

from eagleeye.core.paths import eagleeye_home, reviews_dir, reviews_root


def test_eagleeye_home_defaults_to_dot_eagleeye():
    with patch.dict(os.environ, {}, clear=True):
        assert eagleeye_home() == Path.home() / ".eagleeye"


def test_eagleeye_home_respects_env_override(tmp_path):
    custom = tmp_path / "my-eagleeye"
    with patch.dict(os.environ, {"EAGLEEYE_HOME": str(custom)}, clear=False):
        assert eagleeye_home() == custom


def test_reviews_root_defaults_to_package_parent_reviews():
    root = reviews_root()
    assert root.name == "reviews"
    assert (root.parent / "eagleeye").is_dir()


def test_reviews_root_respects_eagleeye_reviews_dir(tmp_path):
    custom = tmp_path / "custom_reviews"
    with patch.dict(os.environ, {"EAGLEEYE_REVIEWS_DIR": str(custom)}, clear=False):
        assert reviews_root() == custom


def test_reviews_dir_joins_owner_repo_under_root(tmp_path):
    custom = tmp_path / "reviews-out"
    with patch.dict(os.environ, {"EAGLEEYE_REVIEWS_DIR": str(custom)}, clear=False):
        assert reviews_dir("myorg", "myrepo") == custom / "myorg-myrepo"
