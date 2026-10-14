"""Identifiants de publication : uniquement ceux du propriétaire de la chaîne, sans repli global."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.core.api_keys import ApiKeyContext
from agent.skills.publisher import credentials, executor


def _channel(token: str | None = None, page: str | None = "123") -> SimpleNamespace:
    return SimpleNamespace(user_id=uuid.uuid4(), youtube_refresh_token=token, instagram_page_id=page)


def _key(provider: str, key: str | None, metadata: dict | None = None) -> AsyncMock:
    return AsyncMock(return_value=ApiKeyContext(
        user_id=None, provider=provider, key=key, source="user" if key else "none", tier="free", metadata=metadata,
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("own_token", "owner_token", "expected"),
    [("own", "owner", "own"), (None, "owner", "owner"), (None, None, None)],
)
async def test_youtube_token_from_channel_then_owner(own_token, owner_token, expected, monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "global-must-not-be-used")
    channel = _channel(own_token)
    fetch = _key("youtube", owner_token)
    with patch.object(credentials, "fetch_api_key", fetch):
        assert await credentials.youtube_refresh_token(channel) == expected
    if own_token is None:
        assert fetch.await_args.args[:2] == (channel.user_id, "youtube")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "channel_page", "default_page", "expected"),
    [
        ("tok", "123", "999", ("tok", "123")),
        ("tok", None, "999", ("tok", "999")),
        ("tok", None, None, None),
        (None, "123", "999", None),
    ],
)
async def test_instagram_uses_owner_token(token, channel_page, default_page, expected) -> None:
    meta = {"page_id": default_page} if default_page else None
    with patch.object(credentials, "fetch_api_key", _key("instagram", token, meta)):
        creds = await credentials.instagram_credentials(_channel(page=channel_page))
    assert (None if creds is None else (creds.access_token, creds.page_id)) == expected


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
