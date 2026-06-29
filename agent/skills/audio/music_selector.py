from __future__ import annotations

import logging
import random
from pathlib import Path

from agent.skills.audio.music_manifest import is_music_track_allowed, load_music_manifest

logger = logging.getLogger(__name__)

VALID_MOODS = frozenset({
    "energique", "calme", "dramatique", "mysterieux",
    "inspirant", "humoristique", "tension", "revelateur",
})

MUSIC_BASE = Path("./data/music")

# Alias dossiers legacy → moods pipeline
_MOOD_DIR_ALIASES: dict[str, list[str]] = {
    "energique": ["energique", "upbeat"],
    "calme": ["calme", "educational"],
    "dramatique": ["dramatique", "dramatic"],
    "mysterieux": ["mysterieux"],
    "inspirant": ["inspirant", "educational"],
    "humoristique": ["humoristique", "upbeat"],
    "tension": ["tension", "dramatic"],
    "revelateur": ["revelateur", "dramatic", "inspirant"],
}

_FALLBACK_ORDER = ["calme", "inspirant", "energique", "dramatique", "mysterieux"]


def _tracks_in_dir(music_dir: Path, manifest: dict) -> list[Path]:
    if not music_dir.exists():
        return []
    allowed: list[Path] = []
    for path in (*music_dir.glob("*.mp3"), *music_dir.glob("*.wav"), *music_dir.glob("*.ogg")):
        if path.is_file() and path.stat().st_size > 0 and is_music_track_allowed(
            path, manifest, music_base=music_dir.parent
        ):
            allowed.append(path)
    return allowed


def select_music_for_mood(mood: str) -> Path | None:
    """Sélectionne un fichier musical local adapté au mood YouTube/TikTok."""
    manifest = load_music_manifest()
    if not manifest:
        logger.warning("Aucune piste musicale autorisée — manifest vide ou absent")
        return None

    normalized = (mood or "").lower().strip()
    if normalized not in VALID_MOODS:
        normalized = "calme"

    seen_dirs: set[Path] = set()
    candidates: list[str] = list(_MOOD_DIR_ALIASES.get(normalized, [normalized]))
    candidates += [m for m in _FALLBACK_ORDER if m not in candidates]

    for candidate in candidates:
        for dirname in _MOOD_DIR_ALIASES.get(candidate, [candidate]):
            music_dir = MUSIC_BASE / dirname
            if music_dir in seen_dirs:
                continue
            seen_dirs.add(music_dir)
            tracks = _tracks_in_dir(music_dir, manifest)
            if tracks:
                chosen = random.choice(tracks)
                logger.debug("Musique locale sélectionnée : %s (mood=%s)", chosen.name, candidate)
                return chosen

    all_tracks: list[Path] = []
    if MUSIC_BASE.exists():
        for subdir in MUSIC_BASE.iterdir():
            if subdir.is_dir():
                all_tracks.extend(_tracks_in_dir(subdir, manifest))
    if all_tracks:
        chosen = random.choice(all_tracks)
        logger.debug("Musique locale (fallback global) : %s", chosen.name)
        return chosen

    logger.warning("Aucune piste musicale locale autorisée dans %s", MUSIC_BASE)
    return None
