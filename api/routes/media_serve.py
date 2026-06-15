from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import User, get_db
from api.authorization import get_user_project
from api.deps import get_current_user

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("/temp/{project_id}")
async def serve_temp_video(
    project_id: uuid.UUID,
    path: str = Query(..., description="Chemin local encodé de la vidéo"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Expose une vidéo locale via URL authentifiée (publication TikTok via Composio)."""
    await get_user_project(db, project_id, current_user)
    decoded = unquote(path)
    file_path = Path(decoded).resolve()

    allowed_roots = [
        Path("./tmp").resolve(),
        Path("./output").resolve(),
    ]
    if not any(str(file_path).startswith(str(root)) for root in allowed_roots):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chemin non autorisé")

    if not str(file_path).startswith(str(Path("./tmp").resolve() / str(project_id))):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chemin hors projet")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable")

    return FileResponse(file_path, media_type="video/mp4", filename=file_path.name)
