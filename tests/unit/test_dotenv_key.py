"""The API key may come from the project's .env (only the key variables)."""

import pytest

import bondy.config
from bondy.config import load_settings, read_dotenv_key
from bondy.doctor import check_api_key


@pytest.fixture(autouse=True)
def _use_dotenv(monkeypatch):
    monkeypatch.setattr(bondy.config, "DOTENV_FILENAME", ".env")


def _project(tmp_path, env_text, *, git=True):
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    if git:
        (root / ".git").mkdir()
    (root / ".env").write_text(env_text, encoding="utf-8")
    return root


def test_reads_key_from_dotenv_without_exporting(tmp_path):
    root = _project(tmp_path, "OTHER=1\nGOOGLE_API_KEY=abc123\n")
    env: dict[str, str] = {}
    s = load_settings(env=env, start_dir=root / "sub")
    assert s.api_key == "abc123"
    assert s.sources["api_key"] == "dotenv"
    assert env == {}  # nothing exported
    assert "abc123" not in repr(s)


def test_environment_wins_over_dotenv(tmp_path):
    root = _project(tmp_path, "GEMINI_API_KEY=from-file\n")
    s = load_settings(env={"GOOGLE_API_KEY": "from-env"}, start_dir=root)
    assert (s.api_key, s.sources["api_key"]) == ("from-env", "env")


def test_flag_wins_over_dotenv(tmp_path):
    root = _project(tmp_path, "GEMINI_API_KEY=from-file\n")
    s = load_settings(flags={"api_key": "flag"}, env={}, start_dir=root)
    assert (s.api_key, s.sources["api_key"]) == ("flag", "flag")


def test_parsing_quotes_export_bom_crlf_and_comments(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".env").write_bytes(
        b'\xef\xbb\xbf# c\r\nexport GEMINI_API_KEY = "k 1" # note\r\n'
    )
    assert read_dotenv_key(root)[:2] == ("k 1", "GEMINI_API_KEY")
    (root / ".env").write_text("GOOGLE_API_KEY=plain # c\n", encoding="utf-8")
    assert read_dotenv_key(root)[0] == "plain"


def test_gemini_var_has_priority_and_empty_is_ignored(tmp_path):
    root = _project(tmp_path, "GEMINI_API_KEY=\nGOOGLE_API_KEY=g\n")
    assert read_dotenv_key(root)[:2] == ("g", "GOOGLE_API_KEY")


def test_does_not_climb_past_project_root(tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=stray\n", encoding="utf-8")
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    (root / ".git").mkdir()
    assert read_dotenv_key(root / "sub") is None


def test_start_dir_own_dotenv_is_found_without_project_markers(tmp_path):
    child = tmp_path / "a" / "b"
    child.mkdir(parents=True)
    (child / ".env").write_text("GOOGLE_API_KEY=own\n", encoding="utf-8")
    assert read_dotenv_key(child)[0] == "own"


def test_doctor_reports_dotenv_without_value(tmp_path):
    root = _project(tmp_path, "GEMINI_API_KEY=super-secret-value\n")
    c = check_api_key(env={}, start_dir=root)
    assert c.status == "ok"
    assert "super-secret-value" not in c.detail
    assert ".env" in c.detail


def test_unreadable_dotenv_is_absent(tmp_path):
    root = tmp_path / "p"
    (root / ".env").mkdir(parents=True)  # a directory named .env
    (root / ".git").mkdir()
    assert read_dotenv_key(root) is None
