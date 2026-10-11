import pytest

from bondy.config import ConfigError, find_config_file, load_settings, resolve_api_key


def _write(tmp_path, text):
    p = tmp_path / "bondy.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_defaults(tmp_path):
    s = load_settings(env={}, start_dir=tmp_path)
    assert s.model == "gemini-flash-latest"
    assert s.no_llm is False and s.format == "terminal" and s.fail_on == "critical"
    assert s.api_key is None and s.config_path is None
    assert set(s.sources.values()) <= {"default", "unset"}


def test_file_overrides_default(tmp_path):
    _write(tmp_path, 'model = "from-file"\nchecks = ["WCAG 1.1.1"]\nno_llm = true\n')
    s = load_settings(env={}, start_dir=tmp_path)
    assert (s.model, s.checks, s.no_llm) == ("from-file", ["WCAG 1.1.1"], True)
    assert s.sources["model"] == "file"


def test_env_overrides_file(tmp_path):
    _write(tmp_path, 'model = "from-file"\nformat = "terminal"\n')
    s = load_settings(
        env={"BONDY_MODEL": "from-env", "BONDY_CHECKS": "WCAG 1.1.1, WCAG 3.1.1"},
        start_dir=tmp_path,
    )
    assert s.model == "from-env" and s.sources["model"] == "env"
    assert s.checks == ["WCAG 1.1.1", "WCAG 3.1.1"]
    assert s.format == "terminal" and s.sources["format"] == "file"


def test_flag_overrides_env_and_file(tmp_path):
    _write(tmp_path, 'model = "from-file"\n')
    s = load_settings(
        flags={"model": "from-flag", "format": None},
        env={"BONDY_MODEL": "from-env"},
        start_dir=tmp_path,
    )
    assert s.model == "from-flag" and s.sources["model"] == "flag"
    assert s.sources["format"] == "default"  # None flag = not provided


def test_empty_fallback_model_env_disables_it(tmp_path):
    s = load_settings(env={"BONDY_FALLBACK_MODEL": ""}, start_dir=tmp_path)
    assert s.fallback_model == "" and s.sources["fallback_model"] == "env"


def test_api_key_precedence():
    both = {"GEMINI_API_KEY": "gem", "GOOGLE_API_KEY": "goo"}
    assert resolve_api_key(both) == "gem"
    assert resolve_api_key({"GOOGLE_API_KEY": "goo"}) == "goo"
    assert resolve_api_key({"GEMINI_API_KEY": "  ", "GOOGLE_API_KEY": "goo"}) == "goo"
    assert resolve_api_key({}) is None
    s = load_settings(flags={"api_key": "flag"}, env=both, start_dir=".")
    assert s.api_key == "flag" and s.sources["api_key"] == "flag"


def test_api_key_not_in_repr():
    s = load_settings(env={"GEMINI_API_KEY": "super-secret"}, start_dir=".")
    assert s.api_key == "super-secret"
    assert "super-secret" not in repr(s) and "super-secret" not in str(s.sources)


def test_api_key_in_file_is_rejected(tmp_path):
    _write(tmp_path, 'api_key = "x"\n')
    with pytest.raises(ConfigError, match="must not be stored"):
        load_settings(env={}, start_dir=tmp_path)


def test_unknown_key_and_bad_values(tmp_path):
    _write(tmp_path, 'modle = "typo"\n')
    with pytest.raises(ConfigError, match="unknown key"):
        load_settings(env={}, start_dir=tmp_path)
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "bondy.toml").write_text("", encoding="utf-8")  # stops the walk-up
    with pytest.raises(ConfigError, match="fail-on"):
        load_settings(flags={"fail_on": "banana"}, env={}, start_dir=clean)
    with pytest.raises(ConfigError, match="BONDY_NO_LLM"):
        load_settings(env={"BONDY_NO_LLM": "maybe"}, start_dir=clean)


def test_invalid_toml(tmp_path):
    _write(tmp_path, "model = ")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_settings(env={}, start_dir=tmp_path)


def test_find_config_walks_up_and_explicit_path(tmp_path):
    cfg = _write(tmp_path, 'model = "m"\n')
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_config_file(nested) == cfg.resolve()
    assert load_settings(env={}, start_dir=nested).model == "m"
    with pytest.raises(ConfigError, match="not found"):
        load_settings(env={}, config_path=tmp_path / "nope.toml")


def test_env_is_not_modified(tmp_path):
    env = {"BONDY_MODEL": "x"}
    load_settings(env=env, start_dir=tmp_path)
    assert env == {"BONDY_MODEL": "x"}


def test_dotenv_does_not_override_existing_env(tmp_path, monkeypatch):
    """The server loads .env with override=False: real env vars must win."""
    from dotenv import load_dotenv

    dotenv = tmp_path / ".env"
    dotenv.write_text("BONDY_TEST_VAR=from-dotenv\nBONDY_TEST_NEW=new\n")
    monkeypatch.setenv("BONDY_TEST_VAR", "from-env")
    monkeypatch.delenv("BONDY_TEST_NEW", raising=False)
    load_dotenv(dotenv_path=dotenv, override=False)
    import os

    assert os.environ["BONDY_TEST_VAR"] == "from-env"
    assert os.environ["BONDY_TEST_NEW"] == "new"
    monkeypatch.delenv("BONDY_TEST_NEW", raising=False)


def test_server_does_not_use_dotenv_override():
    from pathlib import Path

    src = (Path(__file__).parents[2] / "bondy" / "fast_api_app.py").read_text(
        encoding="utf-8"
    )
    assert "override=True" not in src
