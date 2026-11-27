"""Provider keys fall back to environment variables when none is saved."""

from types import SimpleNamespace

import pytest

from dabba.providers.registry import ProviderRegistry


def _registry(saved_keys=None):
    # resolve_api_key only reads config.api_keys; a stub avoids touching disk.
    registry = ProviderRegistry.__new__(ProviderRegistry)
    registry.config = SimpleNamespace(api_keys=saved_keys or {})
    return registry


@pytest.mark.parametrize(
    "model, env_name",
    [
        ("claude-opus-5-5", "ANTHROPIC_API_KEY"),
        ("gpt-6.2-sol", "OPENAI_API_KEY"),
    ],
)
def test_env_key_used_when_none_saved(monkeypatch, model, env_name):
    monkeypatch.setenv(env_name, "env-value")
    assert _registry().resolve_api_key(model) == ("env-value", env_name)


def test_saved_key_wins_over_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-value")
    registry = _registry({"anthropic": "saved-value"})
    assert registry.resolve_api_key("claude-opus-5-5") == ("saved-value", "anthropic")


def test_no_key_anywhere(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _registry().resolve_api_key("gpt-6.2-sol") == ("", None)
