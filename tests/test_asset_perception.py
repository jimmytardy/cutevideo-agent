from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent.core.montage_plan import ClipMetadata, ClipSegmentMeta
from agent.skills.media.asset_perception import (
    _perception_from_dict,
    compute_file_hash,
    perceive_asset,
    perceive_image,
)
from agent.skills.media.clip_source_analyzer import clip_metadata_from_dict


SAMPLE_PERCEPTION_JSON = {
    "salient_box": [0.2, 0.1, 0.5, 0.6],
    "faces": 1,
    "face_box": [0.3, 0.2, 0.2, 0.3],
    "horizon_y": 0.55,
    "composition": "portrait",
    "energy": 72,
    "emotional_tone": "serein",
    "dominant_colors": ["#1a2b3c", "#ddeeff"],
}


def test_perception_from_dict_maps_fields() -> None:
    meta = _perception_from_dict(SAMPLE_PERCEPTION_JSON)
    assert meta.salient_box == [0.2, 0.1, 0.5, 0.6]
    assert meta.composition == "portrait"
    assert meta.energy == 72
    assert meta.dominant_colors == ["#1a2b3c", "#ddeeff"]


@pytest.mark.asyncio
async def test_perceive_image_async_maps_json(tmp_path: Path) -> None:
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"fake-jpeg")

    with patch("agent.skills.media.asset_perception.asyncio.to_thread", new_callable=AsyncMock) as to_thread:
        to_thread.return_value = SAMPLE_PERCEPTION_JSON
        with patch("google.genai.Client"):
            meta = await perceive_image(image, theme="histoire", api_key="test-key")

    assert meta is not None
    assert meta.salient_box == [0.2, 0.1, 0.5, 0.6]
    assert meta.composition == "portrait"
    assert meta.energy == 72


@pytest.mark.asyncio
async def test_perceive_asset_video_merges_clip_and_frame(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video")

    clip_meta = ClipMetadata(
        motion_score=80,
        useful_duration_s=10.0,
        static_ratio=0.2,
        best_segments=[ClipSegmentMeta(start_s=2.0, end_s=8.0, reason="action")],
        summary="plan large",
    )
    spatial = _perception_from_dict(SAMPLE_PERCEPTION_JSON)

    with patch(
        "agent.skills.media.asset_perception.lookup_perception_by_hash",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with patch(
            "agent.skills.media.asset_perception.analyze_clip_source",
            new_callable=AsyncMock,
            return_value=clip_meta,
        ):
            with patch(
                "agent.skills.media.asset_perception._extract_representative_frame",
                new_callable=AsyncMock,
                return_value=tmp_path / "frame.jpg",
            ):
                with patch(
                    "agent.skills.media.asset_perception.perceive_image",
                    new_callable=AsyncMock,
                    return_value=spatial,
                ):
                    meta, file_hash, cache_hit = await perceive_asset(
                        video,
                        asset_type="video",
                        theme="science",
                        api_key="test-key",
                        context="test context",
                        duration_s=10.0,
                    )

    assert file_hash == compute_file_hash(video)
    assert cache_hit is False
    assert meta is not None
    assert meta.motion_score == 80
    assert meta.best_segments[0].start_s == 2.0
    assert meta.composition == "portrait"
    assert meta.salient_box == [0.2, 0.1, 0.5, 0.6]


@pytest.mark.asyncio
async def test_perceive_asset_cache_hit(tmp_path: Path) -> None:
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"same-bytes")

    cached = _perception_from_dict(SAMPLE_PERCEPTION_JSON)
    perceive_image_mock = AsyncMock(return_value=cached)

    with patch(
        "agent.skills.media.asset_perception.lookup_perception_by_hash",
        new_callable=AsyncMock,
        return_value=cached,
    ):
        with patch(
            "agent.skills.media.asset_perception.perceive_image",
            perceive_image_mock,
        ):
            meta1, _, cache_hit1 = await perceive_asset(
                image,
                asset_type="image",
                theme="art",
                api_key="test-key",
            )
            meta2, _, cache_hit2 = await perceive_asset(
                image,
                asset_type="image",
                theme="art",
                api_key="test-key",
            )

    assert meta1 is not None
    assert meta2 is not None
    assert cache_hit1 is True
    assert cache_hit2 is True
    perceive_image_mock.assert_not_called()


def test_clip_metadata_retrocompat() -> None:
    legacy = {
        "motion_score": 65,
        "useful_duration_s": 12.0,
        "static_ratio": 0.4,
        "best_segments": [{"start_s": 1.0, "end_s": 5.0, "reason": "focus"}],
        "summary": "ancien format",
    }
    meta = clip_metadata_from_dict(legacy)
    assert meta is not None
    assert meta.motion_score == 65
    assert meta.best_segments[0].end_s == 5.0
    assert meta.salient_box is None
    assert meta.faces == 0
    assert meta.dominant_colors == []
