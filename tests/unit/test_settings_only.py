"""P1-1: every Bondy setting is resolved through ``bondy.config``.

Precedence stays flag > environment > bondy.toml > default, and nothing else in
the package reads those environment variables directly.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bondy import config
from bondy.app_utils import vision_tools
from bondy.config import (
    ConfigError,
    export_dotenv_to_environ,
    load_server_settings,
    load_settings,
    load_settings_lenient,
    resolve_api_key,
    use_vertexai,
)

PKG = Path(config.__file__).parent
# Modules allowed to touch the process environment directly:
# - config.py: the single reader of Bondy's variables.
# - doctor.py: `os.environ` only as the default mapping it reports on.
# - telemetry.py: sets OTEL_*/GENAI_* defaults for third-party SDK hooks.
ENV_WHITELIST = {"config.py", "doctor.py", "app_utils/telemetry.py"}
SETTING_VARS = re.compile(
    r"""["']BONDY_(MODEL|VISION_MODEL|FALLBACK_MODEL|API_KEY|APPLY_TOKEN|"""
    r"""ENABLE_AGENT_API|CLOUD_LOGGING)["']"""
)


def _package_sources():
    for path in sorted(PKG.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path, path.read_text(encoding="utf-8")


def _direct_env_reads(tree: ast.AST) -> list[int]:
    """Line numbers of ``os.getenv``/``os.environ``/``getenv``/``environ`` uses."""
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in {"getenv", "environ"}
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            if any(a.name in {"getenv", "environ"} for a in node.names):
                lines.append(node.lineno)
    return lines


def test_no_direct_environment_reads_outside_config():
    offenders = [
        f"{p.relative_to(PKG).as_posix()}:{n}"
        for p, text in _package_sources()
        if p.relative_to(PKG).as_posix() not in ENV_WHITELIST
        for n in _direct_env_reads(ast.parse(text))
    ]
    assert offenders == []


def test_setting_variable_names_live_only_in_config():
    offenders = [
        str(p.relative_to(PKG))
        for p, text in _package_sources()
        if p.relative_to(PKG).as_posix() != "config.py" and SETTING_VARS.search(text)
    ]
    assert offenders == []


# ----- vision tools: models come from Settings at call time -----


def _fake_client(models_used: list[str], fail_first: bool = False):
    client = MagicMock()
    calls = {"n": 0}

    def generate_content(**kw):
        models_used.append(kw["model"])
        calls["n"] += 1
        if fail_first and calls["n"] == 1:
            raise Exception("503 UNAVAILABLE")
        return MagicMock(text="ok")

    client.models.generate_content.side_effect = generate_content
    return client


@pytest.fixture
def clean(monkeypatch, tmp_path):
    for name in ("BONDY_MODEL", "BONDY_VISION_MODEL", "BONDY_FALLBACK_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_models_default(clean):
    assert vision_tools._models() == ("gemini-flash-latest", "gemini-3.5-flash-lite")


def test_vision_model_env_changes_the_model_used_by_generate(clean, monkeypatch):
    monkeypatch.setenv("BONDY_VISION_MODEL", "env-vision")
    monkeypatch.setenv("BONDY_FALLBACK_MODEL", "env-fallback")
    used: list[str] = []
    with patch("google.genai.Client", return_value=_fake_client(used, True)):
        assert vision_tools._generate(["x"]) == "ok"
    assert used == ["env-vision", "env-fallback"]


def test_models_are_read_when_called_not_at_import(clean, monkeypatch):
    assert vision_tools._models()[0] == "gemini-flash-latest"
    monkeypatch.setenv("BONDY_VISION_MODEL", "later")
    assert vision_tools._models()[0] == "later"
    assert not hasattr(vision_tools, "VISION_MODEL")
    assert not hasattr(vision_tools, "FALLBACK_MODEL")


def test_models_precedence_env_over_file_over_default(clean, monkeypatch):
    (clean / "bondy.toml").write_text(
        'vision_model = "file-vision"\nfallback_model = "file-fallback"\n',
        encoding="utf-8",
    )
    assert vision_tools._models() == ("file-vision", "file-fallback")
    monkeypatch.setenv("BONDY_VISION_MODEL", "env-vision")
    assert vision_tools._models() == ("env-vision", "file-fallback")


def test_empty_fallback_env_disables_the_fallback(clean, monkeypatch):
    monkeypatch.setenv("BONDY_FALLBACK_MODEL", "")
    assert vision_tools._models()[1] == ""
    used: list[str] = []
    with (
        patch("google.genai.Client", return_value=_fake_client(used, True)),
        patch.object(vision_tools.time, "sleep"),
        pytest.raises(RuntimeError),
    ):
        vision_tools._generate(["x"])
    assert used == ["gemini-flash-latest"]


def test_broken_toml_does_not_crash_agent_tools(clean, monkeypatch):
    (clean / "bondy.toml").write_text("model = [not toml", encoding="utf-8")
    monkeypatch.setenv("BONDY_VISION_MODEL", "still-env")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert vision_tools._models()[0] == "still-env"
    assert vision_tools._client_kwargs() == {"vertexai": False, "api_key": "k"}
    with pytest.raises(ConfigError):
        load_settings(start_dir=clean)  # the strict loader still reports it


def test_lenient_loader_survives_invalid_values(clean, monkeypatch):
    monkeypatch.setenv("BONDY_BATCH_SIZE", "not-a-number")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    s = load_settings_lenient(start_dir=clean)
    assert s.batch_size == 8 and s.api_key == "k"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("True", True), ("true", True), ("0", False), ("", False)],
)
def test_use_vertexai(value, expected):
    assert use_vertexai({"GOOGLE_GENAI_USE_VERTEXAI": value}) is expected
    assert use_vertexai({}) is False


# ----- agent.py respects BONDY_MODEL -----


def _agent_model(cwd: Path, env_extra: dict[str, str]) -> str:
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith("BONDY_")}
    env.update(env_extra)
    code = (
        "import bondy.agent as a;m = a.root_agent.model; print(getattr(m, 'model', m))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    return proc.stdout.strip().splitlines()[-1]


def test_agent_model_follows_settings(tmp_path):
    pytest.importorskip("google.adk")
    assert _agent_model(tmp_path, {}) == "gemini-flash-latest"
    assert _agent_model(tmp_path, {"BONDY_MODEL": "env-model"}) == "env-model"
    (tmp_path / "bondy.toml").write_text('model = "file-model"\n', encoding="utf-8")
    assert _agent_model(tmp_path, {}) == "file-model"
    assert _agent_model(tmp_path, {"BONDY_MODEL": "env-model"}) == "env-model"


# ----- server settings: the apply token is not the Gemini key -----


def test_apply_token_precedence_and_deprecation():
    s = load_server_settings({})
    assert s.apply_token is None and s.deprecations == ()

    s = load_server_settings({"BONDY_APPLY_TOKEN": "new"})
    assert s.apply_token == "new" and s.deprecations == ()

    s = load_server_settings({"BONDY_API_KEY": "old"})
    assert s.apply_token == "old"  # legacy alias keeps working...
    assert "BONDY_API_KEY is deprecated" in s.deprecations[0]  # ...with a warning

    s = load_server_settings({"BONDY_APPLY_TOKEN": "new", "BONDY_API_KEY": "old"})
    assert s.apply_token == "new"
    assert "takes precedence" in s.deprecations[0]

    assert load_server_settings({"BONDY_API_KEY": ""}).apply_token is None


def test_apply_token_is_not_the_gemini_key():
    env = {"BONDY_API_KEY": "tok", "BONDY_APPLY_TOKEN": "tok2"}
    assert resolve_api_key(env) is None
    assert load_settings(env=env, use_file=False).api_key is None
    gem = {"GEMINI_API_KEY": "g"}
    assert load_server_settings(gem).apply_token is None
    assert "tok" not in repr(load_server_settings(env))  # never printed


def test_server_flags_and_lists():
    s = load_server_settings(
        {
            "BONDY_ENABLE_AGENT_API": "1",
            "BONDY_CLOUD_LOGGING": "1",
            "ALLOW_ORIGINS": "http://a.test, http://b.test,,",
            "LOGS_BUCKET_NAME": "bkt",
        }
    )
    assert s.enable_agent_api and s.cloud_logging
    assert s.allow_origins == ["http://a.test", "http://b.test"]
    assert s.logs_bucket == "bkt"
    d = load_server_settings({"BONDY_ENABLE_AGENT_API": "0", "ALLOW_ORIGINS": ""})
    assert not d.enable_agent_api and d.allow_origins is None and d.logs_bucket is None


def test_fast_api_app_authorization_uses_server_settings(monkeypatch):
    from bondy import fast_api_app

    monkeypatch.delenv("BONDY_API_KEY", raising=False)
    monkeypatch.delenv("BONDY_APPLY_TOKEN", raising=False)
    assert fast_api_app._is_authorized({}, "127.0.0.1")
    assert not fast_api_app._is_authorized({}, "203.0.113.9")

    monkeypatch.setenv("BONDY_APPLY_TOKEN", "new")
    assert fast_api_app._is_authorized({"x-api-key": "new"}, "203.0.113.9")
    assert not fast_api_app._is_authorized({}, "127.0.0.1")

    monkeypatch.delenv("BONDY_APPLY_TOKEN")
    monkeypatch.setenv("BONDY_API_KEY", "old")  # deprecated alias still works
    assert fast_api_app._is_authorized({"x-api-key": "old"}, "203.0.113.9")
    assert not fast_api_app._is_authorized({"x-api-key": "bad"}, "127.0.0.1")


# ----- the server no longer loads the whole .env -----


def test_dotenv_export_is_allowlisted_and_does_not_override(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "GEMINI_API_KEY=gem",
                "export BONDY_VISION_MODEL='m'",
                "BONDY_APPLY_TOKEN=tok",
                "GOOGLE_CLOUD_PROJECT=proj",
                "ALLOW_ORIGINS=http://x.test",
                "LOGS_BUCKET_NAME=b",
                "PATH=/evil",
                "HOME=/evil",
                "SOMETHING_ELSE=1",
                "BONDY_MODEL=file-wins-never",
            ]
        ),
        encoding="utf-8",
    )
    env = {"BONDY_MODEL": "already-set"}
    exported = export_dotenv_to_environ(env_file, env)
    assert env["BONDY_MODEL"] == "already-set"  # override=False
    assert env["GEMINI_API_KEY"] == "gem"
    assert env["BONDY_VISION_MODEL"] == "m"
    assert env["BONDY_APPLY_TOKEN"] == "tok"
    assert env["ALLOW_ORIGINS"] == "http://x.test"
    assert env["LOGS_BUCKET_NAME"] == "b"
    for ignored in ("PATH", "HOME", "SOMETHING_ELSE"):
        assert ignored not in env
    assert "BONDY_MODEL" not in exported


def test_dotenv_export_missing_file_is_noop(tmp_path):
    env: dict[str, str] = {}
    assert export_dotenv_to_environ(tmp_path / "nope.env", env) == []
    assert env == {}
