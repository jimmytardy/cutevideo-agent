"""Tests avertissements durée short dans l'aperçu final."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from agent.core.final_preview import build_duration_warnings, is_short_preview_video_type
from agent.core.database import Video


def _short_video(duration_s: float, video_type: str = "short_tiktok") -> Video:
    return Video(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        video_type=video_type,
        duration_s=duration_s,
        status="approved",
        created_at=datetime.now(timezone.utc),
    )


def test_is_short_preview_video_type() -> None:
    assert is_short_preview_video_type("short_tiktok") is True
    assert is_short_preview_video_type("short_native_1") is True
    assert is_short_preview_video_type("long") is False


def test_build_duration_warnings_short_under_tiktok_min() -> None:
    video = _short_video(55.0)
    warnings = build_duration_warnings(video, min_duration_tiktok=60)
    assert len(warnings) == 1
    assert "55s" in warnings[0]
    assert "60s" in warnings[0]
    assert "TikTok" in warnings[0]


def test_build_duration_warnings_ok_duration() -> None:
    video = _short_video(72.0)
    assert build_duration_warnings(video, min_duration_tiktok=60) == []


def test_build_duration_warnings_ignores_long_video() -> None:
    video = _short_video(30.0, video_type="long")
    assert build_duration_warnings(video, min_duration_tiktok=60) == []
