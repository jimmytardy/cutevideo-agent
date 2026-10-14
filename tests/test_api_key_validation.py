"""Validation des clés : Anthropic n'accepte qu'une clé API (jamais un token d'abonnement Claude.ai)."""

from __future__ import annotations

import pytest

from agent.core.api_key_validation import ApiKeyValidationError, validate_api_key


@pytest.mark.asyncio
async def test_anthropic_subscription_token_is_refused() -> None:
    with pytest.raises(ApiKeyValidationError, match="sk-ant-api"):
        await validate_api_key("anthropic", "sk-ant-oat01-abcdef")


@pytest.mark.asyncio
async def test_instagram_requires_page_id() -> None:
    with pytest.raises(ApiKeyValidationError, match="page_id"):
        await validate_api_key("instagram", "token", {})
