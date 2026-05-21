from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("/temp/{project_id}")
async def serve_temp_video(
    project_id: uuid.UUID,
    path: str = Query(..., description="Chemin local encodé de la vidéo"),
) -> FileResponse:
    """Expose une vidéo locale via URL publique (requis par TikTok via Composio)."""
    decoded = unquote(path)
    file_path = Path(decoded).resolve()

    allowed_roots = [
        Path("./tmp").resolve(),
        Path("./output").resolve(),
    ]
    if not any(str(file_path).startswith(str(root)) for root in allowed_roots):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chemin non autorisé")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable")

    return FileResponse(file_path, media_type="video/mp4", filename=file_path.name)
