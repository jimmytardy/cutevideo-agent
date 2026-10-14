"""Identifiants de publication : le token global n'est prêté qu'aux chaînes admin."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.skills.publisher import credentials, executor


def _channel(token: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(user_id=uuid.uuid4(), youtube_refresh_token=token, instagram_page_id="123")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("own_token", "is_admin", "expected"),
    [("own", False, "own"), (None, False, None), (None, True, "global")],
)
async def test_youtube_token_global_only_for_admin(monkeypatch, own_token, is_admin, expected) -> None:
    monkeypatch.setattr(credentials.settings, "youtube_refresh_token", "global")
    with patch.object(credentials, "channel_owner_is_admin", AsyncMock(return_value=is_admin)):
        assert await credentials.youtube_refresh_token(_channel(own_token)) == expected


@pytest.mark.asyncio
async def test_instagram_refused_for_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(credentials.settings, "instagram_access_token", "global")
    with patch.object(credentials, "channel_owner_is_admin", AsyncMock(return_value=False)):
        assert await credentials.instagram_publishing_allowed(_channel()) is False


@pytest.mark.asyncio
async def test_publication_already_claimed_is_not_uploaded_twice() -> None:
    publication = SimpleNamespace(id=uuid.uuid4(), platform="youtube", title="t", description="", hashtags=[])
    video = SimpleNamespace(id=uuid.uuid4(), file_purged_at=None, storage_key="k", duration_s=30)
    cfg = SimpleNamespace(default_tags=[], min_duration_tiktok=0)
    with (
        patch.object(executor, "_claim_for_publishing", AsyncMock(return_value=False)),
        patch.object(executor, "_publish_youtube", AsyncMock()) as upload,
        patch.object(executor, "_mark_failed", AsyncMock()) as mark_failed,
    ):
        assert await executor.publish_scheduled(publication, SimpleNamespace(slug="c"), cfg, video) is None
    upload.assert_not_awaited()
    mark_failed.assert_not_awaited()
