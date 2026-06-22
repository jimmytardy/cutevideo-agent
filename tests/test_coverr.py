"""Tests module Coverr."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.skills.media_sources import coverr


@pytest.mark.asyncio
async def test_coverr_search_skips_without_api_key() -> None:
    with patch.object(coverr.settings, "coverr_api_key", ""):
        result = await coverr.search(["nature"], media_type="video")
    assert result == []


@pytest.mark.asyncio
async def test_coverr_search_skips_images() -> None:
    with patch.object(coverr.settings, "coverr_api_key", "test-key"):
        result = await coverr.search(["nature"], media_type="image")
    assert result == []


@pytest.mark.asyncio
async def test_coverr_search_parses_vertical_videos() -> None:
    payload = {
        "hits": [
            {
                "id": "abc123",
                "title": "Skateboard fall",
                "is_vertical": True,
                "max_width": 1080,
                "duration": 8.5,
                "thumbnail": "https://example.com/thumb.jpg",
                "urls": {
                    "mp4_download": "https://example.com/video.mp4?token=x",
                },
            },
            {
                "id": "landscape1",
                "title": "Landscape clip",
                "is_vertical": False,
                "urls": {"mp4": "https://example.com/wide.mp4"},
            },
        ],
    }
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=payload)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(coverr.settings, "coverr_api_key", "test-key"),
        patch("agent.skills.media_sources.coverr.aiohttp.ClientSession", return_value=mock_session),
    ):
        result = await coverr.search(
            ["skateboard", "fail"],
            media_type="video",
            orientation="portrait",
        )

    assert len(result) == 1
    assert result[0]["source"] == "coverr"
    assert result[0]["asset_type"] == "video"
    assert result[0]["coverr_video_id"] == "abc123"
    assert result[0]["url"].startswith("https://example.com/video.mp4")


@pytest.mark.asyncio
async def test_coverr_record_download_noop_without_key() -> None:
    with patch.object(coverr.settings, "coverr_api_key", ""):
        await coverr.record_download("abc123")
