from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import Video
from agent.core.subtitle_paths import resolve_project_srt_path


def video_is_streamable(video: Video) -> bool:
    if video.storage_key:
        return True
    if not video.local_path:
        return False
    return Path(video.local_path).is_file()


def _preview_sort_key(video: Video) -> tuple[float, float, float]:
    created = video.created_at.timestamp() if video.created_at else 0.0
    approved = 1.0 if video.status == "approved" else 0.0
    playable = 1.0 if video_is_streamable(video) else 0.0
    return (playable, approved, created)


async def resolve_preview_video(session: AsyncSession, project_id: uuid.UUID) -> Video | None:
    """Vidéo la plus pertinente pour l'aperçu final (streamable, approuvée, récente)."""
    result = await session.execute(
        select(Video)
        .where(Video.project_id == project_id)
        .order_by(Video.created_at.desc())
    )
    videos = list(result.scalars().all())
    if not videos:
        return None
    return max(videos, key=_preview_sort_key)


def subtitles_available_for_video(video: Video | None, project_id: uuid.UUID) -> bool:
    """SRT sidecar — pertinent pour les vidéos longues sans burn-in."""
    if video is None:
        return resolve_project_srt_path(project_id) is not None
    if video.video_type == "long":
        return resolve_project_srt_path(project_id, video_id=video.id) is not None
    if video.video_type == "short_master":
        return False
    if (video.video_type or "").startswith("short_"):
        return False
    return resolve_project_srt_path(project_id, video_id=video.id) is not None


def is_short_preview_video_type(video_type: str | None) -> bool:
    if not video_type:
        return False
    if video_type in ("short_tiktok", "short_master", "short_youtube", "short_instagram"):
        return True
    return video_type.startswith("short_native_") or video_type.startswith("short_")


def build_duration_warnings(
    video: Video,
    *,
    min_duration_tiktok: int,
) -> list[str]:
    if not is_short_preview_video_type(video.video_type):
        return []
    duration = video.duration_s
    if duration is None or duration >= min_duration_tiktok:
        return []
    rounded = int(round(duration))
    return [
        f"Durée {rounded}s < minimum TikTok ({min_duration_tiktok}s) "
        "— publication TikTok bloquée."
    ]
