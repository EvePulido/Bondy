"""Shared test fixtures."""

import pytest

import bondy.config


@pytest.fixture(autouse=True)
def _ignore_project_dotenv(monkeypatch):
    """Keep the developer's real ``.env`` (and its API key) out of every test.

    ``tests/unit/test_dotenv_key.py`` opts back in on temporary directories.
    """
    monkeypatch.setattr(bondy.config, "DOTENV_FILENAME", ".bondy-test-no-dotenv")
