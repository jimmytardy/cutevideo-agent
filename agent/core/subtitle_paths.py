from __future__ import annotations

import uuid
from pathlib import Path


def resolve_project_srt_path(
    project_id: uuid.UUID,
    *,
    video_id: uuid.UUID | None = None,
) -> Path | None:
    """Retourne le fichier .srt du projet s'il existe (sidecar vidéos longues)."""
    output_dir = Path(f"./tmp/{project_id}")
    if not output_dir.is_dir():
        return None

    candidates: list[Path] = []
    if video_id is not None:
        candidates.append(output_dir / f"subtitles_{video_id}.srt")
    candidates.append(output_dir / "subtitles.srt")

    for path in candidates:
        if path.is_file():
            return path

    extra = sorted(
        output_dir.glob("subtitles_*.srt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return extra[0] if extra else None
