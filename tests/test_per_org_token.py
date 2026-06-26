"""Tests for per-org GitHub token resolution."""
import os
from unittest.mock import patch


def _make_config(github_token="global", github_tokens=None):
    """Create a minimal EagleEyeConfig for testing."""
    from eagleeye.config import EagleEyeConfig
    return EagleEyeConfig(
        github_token=github_token,
        github_tokens=github_tokens or {},
        anthropic_api_key="",
        model="claude-sonnet-4-6",
        max_tokens=8192,
        auth_mode="direct",
        proxy_client_id="",
        proxy_client_secret="",
        proxy_url="",
        token_url="",
        scope="",
    )


def test_env_var_takes_priority():
    from eagleeye.config import resolve_github_token
    cfg = _make_config(github_token="global", github_tokens={"acme-corp": "map_token"})
    with patch.dict(os.environ, {"GITHUB_TOKEN_ACME_CORP": "env_token"}):
        assert resolve_github_token("acme-corp", cfg) == "env_token"


def test_toml_map_fallback():
    from eagleeye.config import resolve_github_token
    cfg = _make_config(github_token="global", github_tokens={"acme-corp": "map_token"})
    assert resolve_github_token("acme-corp", cfg) == "map_token"


def test_global_token_fallback():
    from eagleeye.config import resolve_github_token
    cfg = _make_config(github_token="global")
    assert resolve_github_token("unknown-org", cfg) == "global"


def test_hyphens_to_underscores_in_env_key():
    from eagleeye.config import resolve_github_token
    cfg = _make_config(github_token="global")
    # acme-corp → GITHUB_TOKEN_ACME_CORP
    with patch.dict(os.environ, {"GITHUB_TOKEN_ACME_CORP": "env_token"}):
        assert resolve_github_token("acme-corp", cfg) == "env_token"


def test_toml_default_key_fallback():
    from eagleeye.config import resolve_github_token
    cfg = _make_config(github_token="global", github_tokens={"default": "default_map_token"})
    assert resolve_github_token("any-org", cfg) == "default_map_token"
