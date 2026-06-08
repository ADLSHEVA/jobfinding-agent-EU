"""Keep the test suite hermetic and offline.

A real `.env` (with live DeepSeek/Jina/Brave keys) sits in the project root for
manual runs. Without this fixture, `get_settings()` would read it and tests that
exercise the UI / `default_similarity` would make real API calls — spending quota on
every `pytest`. We blank the credential env vars (env vars override the .env file in
pydantic-settings) and clear the settings cache so all tests run with no live config.
"""

import pytest

from job_agent.config import get_settings

_BLANKED = (
    "LLM_API_KEY", "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL",
    "SUPABASE_URL", "SUPABASE_KEY", "BRAVE_API_KEY",
    "KEYWORD_LLM_API_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch):
    for var in _BLANKED:
        monkeypatch.setenv(var, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
