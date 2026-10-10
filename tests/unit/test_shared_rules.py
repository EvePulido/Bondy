"""Debt: shared alt rules live in core; agent-mode tools import them from there."""

import subprocess
import sys

from bondy.app_utils import vision_tools
from bondy.core import alt_rules


def test_agent_tools_reuse_the_core_rules():
    for name in (
        "ALT_SYSTEM_RULES",
        "decorative_heuristics",
        "alt_text_static_checks",
        "decide_alt_recommendation",
        "AltVerdict",
        "REDUNDANT_PREFIX",
    ):
        assert getattr(vision_tools, name) is getattr(alt_rules, name)
    assert vision_tools._quota_retry_delay is alt_rules.quota_retry_delay


def test_core_does_not_import_the_agent_tools_module():
    code = (
        "import sys, bondy.core.pipeline, bondy.core.estimate, "
        "bondy.core.providers.gemini, bondy.doctor, bondy.cli;"
        "assert 'bondy.app_utils.vision_tools' not in sys.modules;"
        "assert not any(m.startswith('google.adk') for m in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_agent_client_gets_the_explicit_key_from_settings(monkeypatch, tmp_path):
    captured = {}

    class FakeClient:
        def __init__(self, **kw):
            captured.update(kw)
            self.models = self

        def generate_content(self, **kw):
            class R:
                text = "ok"

            return R()

    monkeypatch.setattr("google.genai.Client", FakeClient)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "key-from-settings")
    monkeypatch.setenv("GOOGLE_API_KEY", "the-sdk-would-prefer-this")
    monkeypatch.chdir(tmp_path)
    assert vision_tools._generate(["hi"]) == "ok"
    assert captured == {"vertexai": False, "api_key": "key-from-settings"}


def test_agent_client_keeps_environment_credentials_for_vertex(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "True")
    monkeypatch.setenv("GEMINI_API_KEY", "ignored-for-vertex")
    monkeypatch.chdir(tmp_path)
    assert vision_tools._client_kwargs() == {}


def test_agent_client_without_key_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert vision_tools._client_kwargs() == {}
