"""Tests mise à jour chaîne (paramètres dashboard)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.models import ChannelUpdate
from api.routes import channels as channels_route


@pytest.mark.asyncio
async def test_update_channel_preserves_existing_config_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    channel_id = uuid.uuid4()
    user = MagicMock()
    user.is_admin = True

    channel = MagicMock()
    channel.config = {
        "media_source_priority": ["coverr", "pexels"],
        "publishing": {
            "timezone": "Europe/Paris",
            "daily_quotas": {"long": 1, "short": 3},
            "enabled_platforms": ["youtube"],
        },
        "tts": {"engine": "azure", "voice": "fr-FR-DeniseNeural"},
    }
    channel.theme_category = "histoire"
    channel.theme_prompt = "Ancien thème"
    channel.niche_prompt = "Ancienne niche"
    channel.creative_brief = None

    async def fake_get_user_channel(
        db: AsyncMock, cid: uuid.UUID, current_user: MagicMock
    ) -> MagicMock:
        assert cid == channel_id
        assert current_user is user
        return channel

    monkeypatch.setattr(channels_route, "get_user_channel", fake_get_user_channel)

    db = AsyncMock()
    existing = channel.config
    body = ChannelUpdate(
        theme_category="science",
        theme_prompt="Espace et astronomie",
        niche_prompt="Découvertes récentes",
        creative_brief="Ton accessible",
        config={
            **existing,
            "editorial": {"tone": "Pédagogique"},
            "publishing": {
                **existing["publishing"],
                "daily_quotas": {"long": 2, "short": 5},
                "enabled_platforms": ["youtube", "tiktok"],
                "youtube_category_id": "28",
            },
            "tts": {
                **existing["tts"],
                "style": "narration-professional",
                "short": {"engine": "gemini", "voice": "Leda"},
                "long": {"engine": "azure", "voice": "fr-FR-Vivienne:DragonHDLatestNeural"},
            },
        },
    )

    await channels_route.update_channel(channel_id, body, db, user)

    assert channel.theme_category == "science"
    assert channel.theme_prompt == "Espace et astronomie"
    assert channel.niche_prompt == "Découvertes récentes"
    assert channel.creative_brief == "Ton accessible"
    assert channel.config["media_source_priority"] == ["coverr", "pexels"]
    assert channel.config["publishing"]["timezone"] == "Europe/Paris"
    assert channel.config["publishing"]["daily_quotas"] == {"long": 2, "short": 5}
    assert channel.config["editorial"]["tone"] == "Pédagogique"
    assert channel.config["tts"]["short"]["engine"] == "gemini"
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(channel)
