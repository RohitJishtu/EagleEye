"""Configuration loading for EagleEye.

Priority order:
1. Environment variables (GITHUB_TOKEN, ANTHROPIC_API_KEY, EAGLEEYE_MODEL, EAGLEEYE_MAX_TOKENS)
2. ~/.eagleeye/config.yml (auto-migrated from config.toml on first run)
3. .env file in the current working directory (dev convenience)

Auth modes:
  direct — ANTHROPIC_API_KEY required, calls api.anthropic.com directly
  proxy  — PROXY_CLIENT_ID + PROXY_CLIENT_SECRET + EAGLEEYE_PROXY_URL (OAuth2 enterprise proxy)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from cwd for dev convenience (no-op in production)
load_dotenv()

_CONFIG_PATH      = Path.home() / ".eagleeye" / "config.yml"
_CONFIG_PATH_TOML = Path.home() / ".eagleeye" / "config.toml"

# OAuth2 enterprise proxy — set via env when AUTH_MODE=proxy (no baked-in URLs)
_DEFAULT_PROXY_URL = ""
_DEFAULT_TOKEN_URL = ""
_DEFAULT_SCOPE = ""
_DEFAULT_PROXY_MODEL = "claude-sonnet-4-5-20250929"

# Minimum content block size to apply cache_control: ephemeral.
# Anthropic's minimum cacheable block is ~1,024 tokens ≈ 4 KB.
CACHE_CONTENT_THRESHOLD: int = 4_000

# Module-level token cache — avoids exchanging credentials on every API call
_token_cache: dict = {"token": None, "expires_at": 0.0}


class ConfigError(Exception):
    pass


@dataclass
class EagleEyeConfig:
    github_token: str
    anthropic_api_key: str = ""
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192
    auth_mode: str = "direct"       # "direct" | "proxy"
    proxy_client_id: str = ""
    proxy_client_secret: str = ""
    proxy_url: str = _DEFAULT_PROXY_URL
    token_url: str = _DEFAULT_TOKEN_URL
    scope: str = _DEFAULT_SCOPE
    github_tokens: dict = field(default_factory=dict)
    max_files: int = 30
    max_file_bytes: int = 500_000
    max_total_bytes: int = 1000_000
    reference_repos: list[str] = field(default_factory=list)

    def validate_for_claude(self) -> None:
        if self.auth_mode == "proxy":
            if not self.proxy_client_id or not self.proxy_client_id.strip():
                raise ConfigError(
                    "Missing proxy credentials. Add to .env:\n"
                    "  PROXY_CLIENT_ID=your-client-id\n"
                    "  PROXY_CLIENT_SECRET=your-client-secret\n"
                    "  EAGLEEYE_PROXY_URL=https://your-proxy/v1/messages\n"
                    "  EAGLEEYE_PROXY_TOKEN_URL=https://your-idp/oauth/token\n"
                    "Then restart."
                )
            if not self.proxy_client_secret or not self.proxy_client_secret.strip():
                raise ConfigError(
                    "Missing proxy credentials. Add to .env:\n"
                    "  PROXY_CLIENT_ID=your-client-id\n"
                    "  PROXY_CLIENT_SECRET=your-client-secret\n"
                    "Then restart."
                )
            if not self.proxy_url or not self.proxy_url.strip():
                raise ConfigError(
                    "Missing EAGLEEYE_PROXY_URL for AUTH_MODE=proxy."
                )
        else:
            if not self.anthropic_api_key or not self.anthropic_api_key.strip():
                raise ConfigError("Missing ANTHROPIC_API_KEY in .env file.")


def resolve_github_token(owner: str, config: "EagleEyeConfig") -> str:
    """Return the correct GitHub token for the given org owner.

    Priority:
    1. GITHUB_TOKEN_<ORG> env var (hyphens → underscores, uppercase)
    2. config.github_tokens[owner] from [github_tokens] TOML section
    3. config.github_tokens["default"] fallback in map
    4. config.github_token global fallback
    """
    env_key = "GITHUB_TOKEN_" + owner.upper().replace("-", "_")
    env_val = os.getenv(env_key)
    if env_val:
        return env_val
    if config.github_tokens:
        token = config.github_tokens.get(owner) or config.github_tokens.get("default")
        if token:
            return token
    return config.github_token


def get_proxy_token(client_id: str, client_secret: str, token_url: str, scope: str) -> str:
    """Exchange OAuth2 client credentials for a Bearer token. Caches until expiry."""
    global _token_cache
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["token"]

    import httpx
    resp = httpx.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "scope": scope,
        },
        auth=(client_id, client_secret),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["token"]


def load_config(require_claude: bool = True) -> EagleEyeConfig:
    """Load configuration from env vars, falling back to ~/.eagleeye/config.toml."""
    auth_mode = os.environ.get("AUTH_MODE", "direct")
    github_token = os.environ.get("GITHUB_TOKEN")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    proxy_client_id = (
        os.environ.get("PROXY_CLIENT_ID")
        or os.environ.get("SN_CLIENT_ID", "")  # legacy alias
    )
    proxy_client_secret = (
        os.environ.get("PROXY_CLIENT_SECRET")
        or os.environ.get("SN_CLIENT_SECRET", "")
    )
    proxy_url = os.environ.get("EAGLEEYE_PROXY_URL", "")
    token_url = os.environ.get("EAGLEEYE_PROXY_TOKEN_URL", "")
    scope = os.environ.get("EAGLEEYE_PROXY_SCOPE", "")
    default_model = _DEFAULT_PROXY_MODEL if auth_mode == "proxy" else "claude-sonnet-4-6"
    model = os.environ.get("EAGLEEYE_MODEL", default_model)
    max_tokens = int(os.environ.get("EAGLEEYE_MAX_TOKENS", "8192"))

    # Limits — env var wins; 0 means "not set, use TOML/default"
    _env_max_files = int(os.environ.get("EAGLEEYE_MAX_FILES", "0"))
    _env_max_file_bytes = int(os.environ.get("EAGLEEYE_MAX_FILE_BYTES", "0"))
    _env_max_total_bytes = int(os.environ.get("EAGLEEYE_MAX_TOTAL_BYTES", "0"))

    # Always load config once — used for auth fallback and limits fallback
    file_config = _load_yaml_config()
    github_token = github_token or file_config.get("github_token")
    anthropic_api_key = anthropic_api_key or file_config.get("anthropic_api_key", "")
    proxy_client_id = (
        proxy_client_id
        or file_config.get("proxy_client_id")
        or file_config.get("sn_client_id", "")
    )
    proxy_client_secret = (
        proxy_client_secret
        or file_config.get("proxy_client_secret")
        or file_config.get("sn_client_secret", "")
    )
    proxy_url = proxy_url or file_config.get("proxy_url", "")
    token_url = token_url or file_config.get("token_url", "")
    scope = scope or file_config.get("scope", "")
    model = os.environ.get("EAGLEEYE_MODEL") or file_config.get("model", model)
    if not os.environ.get("EAGLEEYE_MAX_TOKENS"):
        max_tokens = int(file_config.get("max_tokens", max_tokens))
    github_tokens: dict = file_config.get("github_tokens", {})

    limits: dict = file_config.get("limits", {})
    max_files = _env_max_files or int(limits.get("max_files", 30))
    max_file_bytes = _env_max_file_bytes or int(limits.get("max_file_bytes", 500_000))
    max_total_bytes = _env_max_total_bytes or int(limits.get("max_total_bytes", 1_000_000))

    ref_cfg: dict = file_config.get("reference", {})
    env_repos = os.environ.get("EAGLEEYE_REFERENCE_REPOS", "")
    if env_repos:
        reference_repos = [r.strip() for r in env_repos.split(",") if r.strip()]
    else:
        reference_repos = list(ref_cfg.get("repos", []) or [])

    if not github_token:
        raise ConfigError(
            "Missing GITHUB_TOKEN.\n\nSet it as an environment variable or run:\n"
            "  eagleeye config init"
        )

    config = EagleEyeConfig(
        github_token=github_token,
        anthropic_api_key=anthropic_api_key,
        model=model,
        max_tokens=max_tokens,
        auth_mode=auth_mode,
        proxy_client_id=proxy_client_id,
        proxy_client_secret=proxy_client_secret,
        proxy_url=proxy_url,
        token_url=token_url,
        scope=scope,
        github_tokens=github_tokens,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        reference_repos=reference_repos,
    )
    if require_claude:
        config.validate_for_claude()
    return config


def _load_toml_config() -> dict:
    """Load ~/.eagleeye/config.toml if it exists."""
    if not _CONFIG_PATH_TOML.exists():
        return {}
    if sys.version_info >= (3, 11):
        import tomllib
        with open(_CONFIG_PATH_TOML, "rb") as f:
            return tomllib.load(f)
    else:
        # Python 3.10 fallback
        try:
            import tomli
            with open(_CONFIG_PATH_TOML, "rb") as f:
                return tomli.load(f)
        except ImportError:
            return {}


def _load_yaml_config() -> dict:
    """Load ~/.eagleeye/config.yml, auto-migrating from .toml on first run."""
    if not _CONFIG_PATH.exists() and _CONFIG_PATH_TOML.exists():
        _migrate_toml_to_yaml()
    if not _CONFIG_PATH.exists():
        return {}
    import yaml
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _migrate_toml_to_yaml() -> None:
    """One-time: read config.toml, write config.yml."""
    toml_data = _load_toml_config()
    if not toml_data:
        return
    import yaml
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        yaml.dump(toml_data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _CONFIG_PATH.chmod(0o600)
    logging.info("Config migrated to %s", _CONFIG_PATH)


def write_config(
    github_token: str,
    anthropic_api_key: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 8192,
) -> Path:
    """Write configuration to ~/.eagleeye/config.yml."""
    import yaml
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "github_token": github_token,
        "anthropic_api_key": anthropic_api_key,
        "model": model,
        "max_tokens": int(max_tokens),
    }
    _CONFIG_PATH.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _CONFIG_PATH.chmod(0o600)
    return _CONFIG_PATH


def _disable_ssl_verification() -> None:
    """Disable SSL certificate verification process-wide.

    Use only for internal corporate deployments whose CA is not in the system trust store.
    urllib3 creates its own SSL context so we must patch requests.Session directly —
    the ssl._create_default_https_context override alone is not enough.
    """
    import ssl
    import warnings

    # stdlib http.client (covers httpx and anything using ssl directly)
    try:
        ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore[attr-defined]
    except Exception:
        pass

    # requests.Session — patch __init__ so every session created after this
    # (including langsmith's internal session) defaults to verify=False
    try:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        _orig_init = requests.Session.__init__

        def _no_verify_init(self, *args, **kwargs):  # type: ignore[misc]
            _orig_init(self, *args, **kwargs)
            self.verify = False

        requests.Session.__init__ = _no_verify_init  # type: ignore[method-assign]
    except Exception:
        pass

    warnings.filterwarnings("ignore", message="Unverified HTTPS request")


def enable_langsmith_tracing() -> None:
    """Enable LangSmith tracing when LANGSMITH_API_KEY or LANGCHAIN_API_KEY is set.

    Supports both LANGSMITH_* (newer SDK) and LANGCHAIN_* (legacy) env var names.
    Set LANGSMITH_ENDPOINT / LANGCHAIN_ENDPOINT to a self-hosted instance.
    Set LANGCHAIN_VERIFY_SSL=false to skip SSL verification (internal corporate CAs).
    """
    api_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    if not api_key:
        return

    # Normalise: LangChain's callback layer reads LANGCHAIN_* vars.
    # Mirror LANGSMITH_* → LANGCHAIN_* so both code paths see the same values.
    os.environ.setdefault("LANGCHAIN_API_KEY", api_key)
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")

    endpoint = os.environ.get("LANGSMITH_ENDPOINT") or os.environ.get("LANGCHAIN_ENDPOINT")
    if endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint
        os.environ["LANGSMITH_ENDPOINT"] = endpoint

    project = os.environ.get("LANGSMITH_PROJECT") or os.environ.get("LANGCHAIN_PROJECT")
    os.environ.setdefault("LANGCHAIN_PROJECT", project or "eagleeye")

    verify = os.environ.get("LANGCHAIN_VERIFY_SSL", "true")
    if verify.lower() in ("false", "0"):
        _disable_ssl_verification()


def show_config(config: EagleEyeConfig) -> dict:
    """Return a config dict with tokens masked for display."""
    def mask(value: str) -> str:
        if len(value) <= 8:
            return "****"
        return value[:4] + "****" + value[-4:]

    result = {
        "github_token": mask(config.github_token),
        "anthropic_api_key": mask(config.anthropic_api_key),
        "model": config.model,
        "max_tokens": config.max_tokens,
    }

    if config.github_tokens:
        result["github_tokens"] = {
            org: mask(tok) for org, tok in config.github_tokens.items()
        }

    return result
