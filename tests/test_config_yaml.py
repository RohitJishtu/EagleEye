import yaml


def test_load_yaml_config_reads_yml(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(yaml.dump({
        "github_token": "ghp_test",
        "anthropic_api_key": "sk-ant-test",
        "model": "claude-sonnet-4-6",
        "reference": {"repo": "myorg/myrepo", "mode": "all"},
    }))
    monkeypatch.setattr("eagleeye.config._CONFIG_PATH", cfg_path)
    monkeypatch.setattr("eagleeye.config._CONFIG_PATH_TOML", tmp_path / "config.toml")
    from eagleeye.config import _load_yaml_config
    data = _load_yaml_config()
    assert data["github_token"] == "ghp_test"
    assert data["reference"]["repo"] == "myorg/myrepo"


def test_migrate_toml_to_yaml(tmp_path, monkeypatch):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('github_token = "ghp_fromtoml"\n')
    yml_path = tmp_path / "config.yml"
    monkeypatch.setattr("eagleeye.config._CONFIG_PATH", yml_path)
    monkeypatch.setattr("eagleeye.config._CONFIG_PATH_TOML", toml_path)
    from eagleeye.config import _load_yaml_config
    data = _load_yaml_config()
    assert yml_path.exists()
    assert "github_token" in data
    assert data["github_token"] == "ghp_fromtoml"


def test_reference_fields_in_eagleeye_config():
    from eagleeye.config import EagleEyeConfig
    cfg = EagleEyeConfig(github_token="ghp_test")
    assert cfg.reference_repos == []


def test_write_config_writes_yaml(tmp_path, monkeypatch):
    yml_path = tmp_path / "config.yml"
    monkeypatch.setattr("eagleeye.config._CONFIG_PATH", yml_path)
    from eagleeye.config import write_config
    write_config("ghp_test", "sk-ant-test")
    assert yml_path.exists()
    data = yaml.safe_load(yml_path.read_text())
    assert data["github_token"] == "ghp_test"
    assert data["anthropic_api_key"] == "sk-ant-test"
