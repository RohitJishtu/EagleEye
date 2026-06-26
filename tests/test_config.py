"""Tests for eagleeye.config."""

import pytest
from pathlib import Path
from unittest.mock import patch

from eagleeye.config import ConfigError, load_config, write_config


def test_load_config_from_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "direct")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test456")
    monkeypatch.setenv("EAGLEEYE_MODEL", "claude-haiku-4-5-20251001")

    config = load_config()

    assert config.github_token == "ghp_test123"
    assert config.anthropic_api_key == "sk-ant-test456"
    assert config.model == "claude-haiku-4-5-20251001"


def test_load_config_missing_github_raises(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "direct")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with patch("eagleeye.config._CONFIG_PATH", Path("/tmp/nonexistent_eagleeye_config.toml")):
        with pytest.raises(ConfigError) as exc_info:
            load_config()

    assert "GITHUB_TOKEN" in str(exc_info.value)


def test_load_config_missing_anthropic_only(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "direct")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with patch("eagleeye.config._CONFIG_PATH", Path("/tmp/nonexistent_eagleeye_config.toml")):
        with pytest.raises(ConfigError) as exc_info:
            load_config()

    assert "ANTHROPIC_API_KEY" in str(exc_info.value)


def test_load_config_proxy_mode_missing_credentials(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "proxy")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.delenv("PROXY_CLIENT_ID", raising=False)
    monkeypatch.delenv("PROXY_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("SN_CLIENT_ID", raising=False)
    monkeypatch.delenv("SN_CLIENT_SECRET", raising=False)

    with patch("eagleeye.config._CONFIG_PATH", Path("/tmp/nonexistent_eagleeye_config.toml")):
        with pytest.raises(ConfigError) as exc_info:
            load_config()

    assert "PROXY_CLIENT_ID" in str(exc_info.value)


def test_write_config_creates_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    with patch("eagleeye.config._CONFIG_PATH", config_path):
        write_config("ghp_abc", "sk-ant-xyz", "claude-sonnet-4-6")

    assert config_path.exists()
    content = config_path.read_text()
    assert "ghp_abc" in content
    assert "sk-ant-xyz" in content
    assert "claude-sonnet-4-6" in content


def test_default_model_direct(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "direct")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-y")
    monkeypatch.delenv("EAGLEEYE_MODEL", raising=False)
    # Isolate from ~/.eagleeye/config.yml which may have a model override
    monkeypatch.setattr("eagleeye.config._CONFIG_PATH", tmp_path / "config.yml")
    monkeypatch.setattr("eagleeye.config._CONFIG_PATH_TOML", tmp_path / "config.toml")

    config = load_config()
    assert config.model == "claude-sonnet-4-6"


def test_default_model_proxy(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "proxy")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("PROXY_CLIENT_ID", "cid")
    monkeypatch.setenv("PROXY_CLIENT_SECRET", "csec")
    monkeypatch.setenv("EAGLEEYE_PROXY_URL", "https://proxy.example.com/v1/messages")
    monkeypatch.setenv("EAGLEEYE_PROXY_TOKEN_URL", "https://idp.example.com/oauth/token")
    monkeypatch.delenv("EAGLEEYE_MODEL", raising=False)

    config = load_config()
    assert config.model == "claude-sonnet-4-5-20250929"
    assert config.auth_mode == "proxy"
