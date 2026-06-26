from eagleeye.config import load_config


def test_reference_repos_from_env(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "direct")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    monkeypatch.setenv("EAGLEEYE_REFERENCE_REPOS", "org/a, org/b ,org/c")
    monkeypatch.setattr("eagleeye.config._load_yaml_config", lambda: {})
    cfg = load_config()
    assert cfg.reference_repos == ["org/a", "org/b", "org/c"]


def test_reference_repos_default_empty(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "direct")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    monkeypatch.delenv("EAGLEEYE_REFERENCE_REPOS", raising=False)
    monkeypatch.setattr("eagleeye.config._load_yaml_config", lambda: {})
    cfg = load_config()
    assert cfg.reference_repos == []


def test_reference_repos_from_yaml(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "direct")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    monkeypatch.delenv("EAGLEEYE_REFERENCE_REPOS", raising=False)
    monkeypatch.setattr(
        "eagleeye.config._load_yaml_config",
        lambda: {"reference": {"repos": ["org/x", "org/y"]}},
    )
    cfg = load_config()
    assert cfg.reference_repos == ["org/x", "org/y"]
