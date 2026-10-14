"""Médias d'un projet : vidéos (liste, stream), aperçu final, miniatures."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import Channel, User, Video, get_db
from api.authorization import get_user_project
from api.deps import get_current_user
from api.models import FinalPreviewResponse, ThumbnailCandidateResponse, VideoResponse

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("/{project_id}/videos", response_model=list[VideoResponse])
async def list_project_videos(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[VideoResponse]:
    await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(Video).where(Video.project_id == project_id).order_by(Video.created_at.desc())
    )
    return [VideoResponse.model_validate(v) for v in result.scalars().all()]


@router.get("/{project_id}/videos/{video_id}/stream", response_model=None)
async def stream_video(
    project_id: uuid.UUID,
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse | RedirectResponse:
    await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(Video).where(Video.id == video_id, Video.project_id == project_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vidéo introuvable")

    if video.local_path:
        local = Path(video.local_path)
        if local.exists():
            return FileResponse(str(local), media_type="video/mp4")

    if video.storage_key:
        from agent.core.storage import generate_presigned_url
        url = await generate_presigned_url(video.storage_key)
        return RedirectResponse(url)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier vidéo introuvable (ni local ni S3)")


@router.get("/{project_id}/final-preview", response_model=FinalPreviewResponse)
async def get_final_preview(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FinalPreviewResponse:
    from agent.core.final_preview import build_duration_warnings, resolve_preview_video
    from agent.core.channel_config import resolve_channel_config

    project = await get_user_project(db, project_id, current_user)

    video = await resolve_preview_video(db, project_id)
    if video is None:
        return FinalPreviewResponse(video=None, stream_url=None)

    channel_result = await db.execute(select(Channel).where(Channel.id == project.channel_id))
    channel = channel_result.scalar_one_or_none()
    duration_warnings: list[str] = []
    if channel is not None:
        channel_config = resolve_channel_config(channel)
        duration_warnings = build_duration_warnings(
            video,
            min_duration_tiktok=channel_config.min_duration_tiktok,
        )

    return FinalPreviewResponse(
        video=VideoResponse.model_validate(video),
        stream_url=f"/api/v1/projects/{project_id}/videos/{video.id}/stream",
        duration_warnings=duration_warnings,
    )


@router.get("/{project_id}/thumbnails", response_model=list[ThumbnailCandidateResponse])
async def get_project_thumbnails(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ThumbnailCandidateResponse]:
    project = await get_user_project(db, project_id, current_user)
    raw = (project.config or {}).get("thumbnail_candidates")
    if not isinstance(raw, list):
        return []
    return [ThumbnailCandidateResponse.model_validate(item) for item in raw if isinstance(item, dict)]


@router.get("/{project_id}/thumbnails/{index}/stream", response_model=None)
async def stream_project_thumbnail(
    project_id: uuid.UUID,
    index: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    project = await get_user_project(db, project_id, current_user)
    raw = (project.config or {}).get("thumbnail_candidates")
    if not isinstance(raw, list) or index < 0 or index >= len(raw):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Miniature introuvable")
    item = raw[index]
    if not isinstance(item, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Miniature introuvable")
    local_path = item.get("local_path")
    if not local_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier miniature absent")
    file_path = Path(str(local_path)).resolve()
    allowed_roots = [
        Path("./tmp").resolve(),
        Path("./output").resolve(),
    ]
    if not any(str(file_path).startswith(str(root)) for root in allowed_roots):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chemin non autorisé")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable")
    return FileResponse(str(file_path), media_type=_media_type_for_path(file_path))


_MEDIA_TYPE_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _media_type_for_path(path: Path) -> str:
    return _MEDIA_TYPE_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
