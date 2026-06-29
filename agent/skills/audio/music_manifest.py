from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MUSIC_MANIFEST_PATH = Path("./data/music/manifest.json")


def load_music_manifest() -> dict[str, dict[str, Any]]:
    if not MUSIC_MANIFEST_PATH.exists():
        logger.warning("Manifest musique absent : %s — aucune piste locale autorisée", MUSIC_MANIFEST_PATH)
        return {}
    try:
        raw = json.loads(MUSIC_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Manifest musique illisible : %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        license_val = str(value.get("license") or "").strip()
        if not license_val:
            continue
        entries[str(key).replace("\\", "/")] = value
    return entries


def music_track_manifest_key(
    track_path: Path,
    music_base: Path | None = None,
) -> str:
    base = (music_base or Path("./data/music")).resolve()
    try:
        rel = track_path.resolve().relative_to(base)
    except ValueError:
        rel = track_path.name
    return str(rel).replace("\\", "/")


def is_music_track_allowed(
    track_path: Path,
    manifest: dict[str, dict[str, Any]] | None = None,
    *,
    music_base: Path | None = None,
) -> bool:
    manifest = manifest if manifest is not None else load_music_manifest()
    if not manifest:
        return False
    key = music_track_manifest_key(track_path, music_base=music_base)
    entry = manifest.get(key)
    if not entry:
        return False
    return bool(str(entry.get("license") or "").strip())
