"""Tests statistiques run MediaAgent."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from agent.agents.media_agent import MediaAgent


def test_build_media_run_stats() -> None:
    video = MagicMock(asset_type="video", source="coverr")
    stock_image = MagicMock(asset_type="image", source="pexels")
    ai_image = MagicMock(asset_type="image", source="ai_image")

    stats = MediaAgent._build_media_run_stats(
        [video, stock_image, ai_image],
        ai_images_used=2,
    )

    assert stats["video_assets_count"] == 1
    assert stats["image_assets_count"] == 1
    assert stats["ai_generated_count"] == 1
    assert stats["ai_images_used"] == 2
    assert stats["coverr_hits"] == 1


def test_resolve_search_orientation_portrait_for_derivation() -> None:
    ctx = MagicMock()
    ctx.derivation_short_index = 0
    assert MediaAgent._resolve_search_orientation(ctx) == "portrait"


def test_resolve_search_orientation_landscape_default() -> None:
    ctx = MagicMock()
    ctx.derivation_short_index = None
    with patch.object(MediaAgent, "_requires_vertical", return_value=False):
        assert MediaAgent._resolve_search_orientation(ctx) == "landscape"
