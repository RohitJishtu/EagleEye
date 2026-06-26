import os
from unittest.mock import patch


def test_default_limits():
    from eagleeye.config import load_config
    env_overrides = {
        "AUTH_MODE": "direct",
        "GITHUB_TOKEN": "ghp_test",
        "ANTHROPIC_API_KEY": "sk-test",
    }
    with patch.dict(os.environ, env_overrides, clear=False):
        # Remove limit env vars so defaults apply regardless of caller's shell
        for k in ["EAGLEEYE_MAX_FILES", "EAGLEEYE_MAX_FILE_BYTES", "EAGLEEYE_MAX_TOTAL_BYTES"]:
            os.environ.pop(k, None)
        config = load_config()
    assert config.max_files == 30
    assert config.max_file_bytes == 500_000
    assert config.max_total_bytes == 1_000_000


def test_env_var_overrides():
    from eagleeye.config import load_config
    env = {
        "AUTH_MODE": "direct",
        "GITHUB_TOKEN": "ghp_test",
        "ANTHROPIC_API_KEY": "sk-test",
        "EAGLEEYE_MAX_FILES": "50",
        "EAGLEEYE_MAX_FILE_BYTES": "20000",
        "EAGLEEYE_MAX_TOTAL_BYTES": "300000",
    }
    with patch.dict(os.environ, env, clear=False):
        config = load_config()
    assert config.max_files == 50
    assert config.max_file_bytes == 20_000
    assert config.max_total_bytes == 300_000


def test_env_overrides_toml(tmp_path, monkeypatch):
    import yaml
    yaml_content = {
        "github_token": "ghp_test",
        "anthropic_api_key": "sk-test",
        "limits": {"max_files": 25},
    }
    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.dump(yaml_content))
    monkeypatch.setattr("eagleeye.config._CONFIG_PATH", config_path)
    monkeypatch.setattr("eagleeye.config._CONFIG_PATH_TOML", tmp_path / "config.toml")

    import eagleeye.config as cfg_module
    for k in ["EAGLEEYE_MAX_FILES", "EAGLEEYE_MAX_FILE_BYTES", "EAGLEEYE_MAX_TOTAL_BYTES",
              "GITHUB_TOKEN", "ANTHROPIC_API_KEY"]:
        os.environ.pop(k, None)

    env = {
        "EAGLEEYE_MAX_FILES": "99",
        "AUTH_MODE": "direct",
        "GITHUB_TOKEN": "ghp_test",
        "ANTHROPIC_API_KEY": "sk-ant-test",
    }
    with patch.dict(os.environ, env, clear=False):
        config = cfg_module.load_config()
    # env var (99) beats YAML (25)
    assert config.max_files == 99
