from __future__ import annotations

from pathlib import Path

from agent.core.database import Video


async def resolve_video_local_path(video: Video) -> Path | None:
    """Retourne le chemin local d'une vidéo, en la retéléchargeant depuis S3 si nécessaire."""
    if video.local_path:
        local = Path(video.local_path)
        if local.exists():
            return local

    if not video.storage_key:
        return Path(video.local_path) if video.local_path else None

    from agent.core.storage import resolve_local_path_for_upload

    return await resolve_local_path_for_upload(video)
