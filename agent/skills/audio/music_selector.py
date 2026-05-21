from __future__ import annotations

import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

MUSIC_DIRS = {
    "educational": Path("./data/music/educational"),
    "dramatic": Path("./data/music/dramatic"),
    "upbeat": Path("./data/music/upbeat"),
}

PERIOD_MOOD_MAP: dict[str, str] = {
    "antiquité": "dramatic",
    "moyen-âge": "dramatic",
    "moderne": "educational",
    "contemporain": "educational",
    "n/a": "educational",
}


def select_music_for_period(historical_period: str) -> Path | None:
    """Sélectionne un fichier musical CC adapté à la période historique."""
    period_lower = (historical_period or "").lower()
    mood = PERIOD_MOOD_MAP.get(period_lower, "educational")
    music_dir = MUSIC_DIRS.get(mood, MUSIC_DIRS["educational"])

    if not music_dir.exists():
        logger.warning("Dossier musique introuvable : %s", music_dir)
        return None

    tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav"))
    if not tracks:
        logger.warning("Aucune piste dans %s", music_dir)
        return None

    return random.choice(tracks)
