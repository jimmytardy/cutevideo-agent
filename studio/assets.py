"""Constantes partagées du rendu Studio (format Short vertical)."""

from __future__ import annotations

import os

SHORT_WIDTH = 1080
SHORT_HEIGHT = 1920
SHORT_FPS = 30


def max_ai_images() -> int:
    """Plafond d'images IA par Short (STUDIO_MAX_AI_IMAGES, abaissé par chaîne via le launcher)."""
    try:
        return max(0, int(os.getenv("STUDIO_MAX_AI_IMAGES", "4")))
    except ValueError:
        return 4
