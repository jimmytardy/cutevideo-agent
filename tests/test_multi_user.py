"""Tests multi-utilisateurs : auth, abonnements, clés API, isolation."""

from __future__ import annotations

import uuid

import pytest

from agent.core.api_keys import (
    decrypt_api_key,
    encrypt_api_key,
    format_api_key_hint,
    resolve_api_key,
)
from agent.core.auth import create_access_token, decode_access_token, create_oauth_state, decode_oauth_state
from agent.core.subscription import (
    SubscriptionLimits,
    apply_subscription_caps,
    is_unlimited,
)
from agent.core.database import SubscriptionPlan


def test_jwt_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id, expires_minutes=30)
    assert decode_access_token(token) == user_id


def test_oauth_state_roundtrip() -> None:
    user_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    state = create_oauth_state(user_id=user_id, channel_id=channel_id, purpose="youtube_connect")
    payload = decode_oauth_state(state, expected_purpose="youtube_connect")
    assert payload["user_id"] == str(user_id)
    assert payload["channel_id"] == str(channel_id)


def test_resolve_login_redirect_appends_login_path() -> None:
    from api.routes.auth import _resolve_login_redirect

    assert _resolve_login_redirect({"redirect_after": "http://localhost:3333"}) == "http://localhost:3333/login"
    assert (
        _resolve_login_redirect({"redirect_after": "http://localhost:3333/login"})
        == "http://localhost:3333/login"
    )
    assert (
        _resolve_login_redirect({"redirect_after": "http://localhost:3333/login?foo=bar"})
        == "http://localhost:3333/login?foo=bar"
    )


def test_api_key_encryption_roundtrip() -> None:
    plain = "sk-test-key-12345"
    encrypted = encrypt_api_key(plain)
    assert decrypt_api_key(encrypted) == plain


def test_format_api_key_hint() -> None:
    assert format_api_key_hint("sk-test-key-12345") == "sk-test-…"
    assert format_api_key_hint("short") == "short"
    assert format_api_key_hint("  abcdefgh  ") == "abcdefgh"


def test_subscription_apply_caps() -> None:
    limits = SubscriptionLimits(
        max_channels=1,
        daily_quotas_short=1,
        max_critic_iterations=2,
        auto_publish_allowed=False,
        production_modes=["shorts_only"],
        tts_allowed_engines=["edge"],
        whisper_model="base",
    )
    cfg = {
        "publishing": {"daily_quotas": {"short": 5}, "auto_publish": True},
        "pipeline": {"max_critic_iterations": 5},
        "production": {"mode": "mixed"},
        "tts": {"engine": "azure"},
        "whisper": {"model": "large-v3"},
        "media_sources": {
            "enable_ai_fallback": True,
            "ai_fallback": {"enabled": True, "plan": "flux_pro"},
        },
    }
    capped = apply_subscription_caps(cfg, limits)
    assert capped["publishing"]["daily_quotas"]["short"] == 1
    assert capped["publishing"]["auto_publish"] is False
    assert capped["pipeline"]["max_critic_iterations"] == 2
    assert capped["production"]["mode"] == "shorts_only"
    assert capped["tts"]["engine"] == "edge"
    assert capped["whisper"]["model"] == "base"
    assert capped["media_sources"]["enable_ai_fallback"] is False
    assert capped["media_sources"]["ai_fallback"]["enabled"] is False


def test_subscription_apply_caps_ai_fallback_allowed() -> None:
    limits = SubscriptionLimits(enable_ai_fallback=True)
    cfg = {
        "media_sources": {
            "enable_ai_fallback": False,
            "ai_fallback": {"enabled": False},
        },
    }
    capped = apply_subscription_caps(cfg, limits)
    assert capped["media_sources"]["enable_ai_fallback"] is True
    assert capped["media_sources"]["ai_fallback"]["enabled"] is False


def test_admin_plan_unlimited() -> None:
    plan = SubscriptionPlan(
        id=uuid.uuid4(),
        slug="admin",
        name="Admin",
        is_unlimited=True,
        limits={},
    )
    assert is_unlimited(plan) is True


@pytest.mark.asyncio
async def test_first_real_user_gets_admin_plan() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from api.routes.auth import MIGRATION_SYSTEM_GOOGLE_SUB, _get_plan_for_new_user

    admin_plan = SubscriptionPlan(
        id=uuid.uuid4(),
        slug="admin",
        name="Admin",
        is_unlimited=True,
        limits={},
    )
    free_plan = SubscriptionPlan(
        id=uuid.uuid4(),
        slug="free",
        name="Gratuit",
        is_unlimited=False,
        limits={},
    )

    session = AsyncMock()

    def make_count_result(count: int) -> MagicMock:
        return MagicMock(scalar_one=MagicMock(return_value=count))

    def make_plan_result(plan: SubscriptionPlan) -> MagicMock:
        return MagicMock(scalar_one_or_none=MagicMock(return_value=plan))

    session.execute = AsyncMock(
        side_effect=[
            make_count_result(0),
            make_plan_result(admin_plan),
            make_count_result(1),
            make_plan_result(free_plan),
        ]
    )

    first_plan = await _get_plan_for_new_user(session)
    second_plan = await _get_plan_for_new_user(session)

    assert first_plan.slug == "admin"
    assert second_plan.slug == "free"
    assert MIGRATION_SYSTEM_GOOGLE_SUB == "migration-system"


@pytest.mark.asyncio
async def test_resolve_gemini_user_key_over_platform() -> None:
    from unittest.mock import AsyncMock, MagicMock

    user_id = uuid.uuid4()
    user_row = MagicMock()
    user_row.encrypted_key = encrypt_api_key("AIza-user-key")
    user_row.metadata_ = None

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=user_row))
    )

    ctx = await resolve_api_key(
        session,
        user_id,
        "gemini",
        purpose="media_relevance_scoring",
        tier="free",
    )
    assert ctx.source == "user"
    assert ctx.key == "AIza-user-key"


@pytest.mark.asyncio
async def test_resolve_gemini_platform_free() -> None:
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    ctx = await resolve_api_key(
        session,
        uuid.uuid4(),
        "gemini",
        purpose="media_relevance_scoring",
        tier="free",
    )
    # Sans clé user : plateforme ou none selon .env
    assert ctx.provider == "gemini"
    assert ctx.source in ("platform", "none")
