"""Tests résolution provider/modèle LLM."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from agent.core.llm_resolver import (
    AgentLlmPreference,
    FREE_GEMINI_MODEL,
    _resolve_gemini_model,
    resolve_llm_call,
)


def test_resolve_gemini_model_rejects_claude_override() -> None:
    model = _resolve_gemini_model(
        "scenario_media_gap",
        pref=AgentLlmPreference(provider="gemini", model="claude-sonnet-4-5", tier="free"),
        model_override="claude-sonnet-4-5",
        tier="free",
    )
    assert model.startswith("gemini-")
    assert model == FREE_GEMINI_MODEL


def test_resolve_gemini_model_keeps_valid_gemini_override() -> None:
    model = _resolve_gemini_model(
        "critic_agent",
        pref=AgentLlmPreference(provider="gemini", model=FREE_GEMINI_MODEL, tier="paid"),
        model_override="gemini-2.5-pro",
        tier="paid",
    )
    assert model == "gemini-2.5-pro"


@pytest.mark.asyncio
async def test_resolve_llm_call_claude_override_with_gemini_user_key() -> None:
    user_id = uuid.uuid4()
    pref = AgentLlmPreference(provider="gemini", model="gemini-2.5-flash", tier="paid")

    class FakeUser:
        id = user_id
        agent_llm_preferences = {"scenario_media_gap": pref.to_dict() if hasattr(pref, "to_dict") else {
            "provider": pref.provider,
            "model": pref.model,
            "tier": pref.tier,
        }}

    fake_user = FakeUser()
    fake_user.agent_llm_preferences = {
        "scenario_media_gap": {"provider": "gemini", "model": "gemini-2.5-flash", "tier": "paid"}
    }

    session = AsyncMock()

    async def fake_resolve_api_key(_session, uid, provider, *, purpose, tier="free"):
        from agent.core.api_keys import ApiKeyContext

        if provider == "anthropic":
            return ApiKeyContext(user_id=uid, provider=provider, key=None, source="none", tier=tier)
        if provider == "gemini":
            return ApiKeyContext(
                user_id=uid,
                provider=provider,
                key="gemini-test-key",
                source="user",
                tier=tier,
            )
        raise AssertionError(provider)

    with patch("agent.core.llm_resolver._has_user_key", new_callable=AsyncMock) as mock_has_key:
        mock_has_key.side_effect = lambda _session, _uid, provider: provider == "gemini"
        with patch("agent.core.llm_resolver.resolve_api_key", side_effect=fake_resolve_api_key):
            cfg = await resolve_llm_call(
                session,
                fake_user,  # type: ignore[arg-type]
                "scenario_media_gap",
                model_override="claude-sonnet-4-5",
            )

    assert cfg.provider == "gemini"
    assert cfg.model.startswith("gemini-")
    assert cfg.model != "claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_resolve_llm_call_claude_override_with_anthropic_key() -> None:
    user_id = uuid.uuid4()

    class FakeUser:
        id = user_id
        agent_llm_preferences = None

    session = AsyncMock()

    async def fake_resolve_api_key(_session, uid, provider, *, purpose, tier="free"):
        from agent.core.api_keys import ApiKeyContext

        if provider == "anthropic":
            return ApiKeyContext(
                user_id=uid,
                provider=provider,
                key="anthropic-test-key",
                source="user",
                tier="paid",
            )
        return ApiKeyContext(user_id=uid, provider=provider, key=None, source="none", tier=tier)

    with patch("agent.core.llm_resolver._has_user_key", new_callable=AsyncMock) as mock_has_key:
        mock_has_key.side_effect = lambda _session, _uid, provider: provider == "anthropic"
        with patch("agent.core.llm_resolver.resolve_api_key", side_effect=fake_resolve_api_key):
            cfg = await resolve_llm_call(
                session,
                FakeUser(),  # type: ignore[arg-type]
                "scenario_media_gap",
                model_override="claude-sonnet-4-5",
            )

    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-sonnet-4-5"
