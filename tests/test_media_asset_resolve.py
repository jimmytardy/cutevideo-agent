"""Tests résolution médias (aperçu images IA S3)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.core.media_asset_resolve import (
    clip_metadata_for_media_item,
    find_existing_local_path,
    local_path_candidates,
    resolve_media_asset_stream_target,
    storage_key_for_asset,
    temp_s3_keys_for_segment,
)


def test_local_path_candidates_relative_to_app_root() -> None:
    paths = local_path_candidates("tmp/proj/media/segment_01/ai_abcd.jpg")
    assert Path("/app/tmp/proj/media/segment_01/ai_abcd.jpg") in paths


def test_storage_key_prefers_clip_metadata() -> None:
    asset = SimpleNamespace(
        source="ai_image",
        segment_order=2,
        clip_metadata={"temp_s3_key": "cutevideo/temp/channel/p1/ai/2/abc.jpg"},
    )
    assert storage_key_for_asset(asset, {"temp_ai_image_keys": ["other"]}) == (
        "cutevideo/temp/channel/p1/ai/2/abc.jpg"
    )


def test_storage_key_fallback_to_project_temp_keys() -> None:
    asset = SimpleNamespace(source="ai_image", segment_order=3, clip_metadata=None)
    config = {"temp_ai_image_keys": ["cutevideo/temp/ch/p/ai/3/winner.jpg"]}
    assert storage_key_for_asset(asset, config) == "cutevideo/temp/ch/p/ai/3/winner.jpg"


def test_clip_metadata_for_media_item() -> None:
    meta = clip_metadata_for_media_item({"_temp_s3_key": "k1"})
    assert meta == {"temp_s3_key": "k1"}


@pytest.mark.asyncio
async def test_resolve_media_asset_stream_target_redirects_to_s3(tmp_path) -> None:
    asset = SimpleNamespace(
        local_path=str(tmp_path / "missing.jpg"),
        source="ai_image",
        segment_order=1,
        source_url=None,
        clip_metadata={"temp_s3_key": "cutevideo/temp/ch/p/ai/1/x.jpg"},
    )
    with (
        patch(
            "agent.core.media_asset_resolve.is_s3_storage_enabled",
            return_value=True,
        ),
        patch(
            "agent.core.media_asset_resolve.get_presigned_url",
            new=AsyncMock(return_value="https://s3.example/presigned"),
        ),
    ):
        target = await resolve_media_asset_stream_target(asset, {})
    assert target == ("redirect", "https://s3.example/presigned")


def test_find_existing_local_path(tmp_path) -> None:
    image = tmp_path / "ai_test.jpg"
    image.write_bytes(b"jpg")
    assert find_existing_local_path(str(image)) == image


def test_temp_s3_keys_for_segment_filters_by_order() -> None:
    config = {
        "temp_ai_image_keys": [
            "cutevideo/temp/ch/p/ai/1/a.jpg",
            "cutevideo/temp/ch/p/ai/2/b.jpg",
        ]
    }
    assert temp_s3_keys_for_segment(config, 2) == ["cutevideo/temp/ch/p/ai/2/b.jpg"]
