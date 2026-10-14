"""Constantes partagées du rendu Studio (format Short vertical)."""

from __future__ import annotations

from agent.core.env import env_int

from pathlib import Path

SHORT_WIDTH = 1080
SHORT_HEIGHT = 1920
SHORT_FPS = 30

# Kit d'animation et polices copiés dans chaque run dir (studio/workspace/anim/lib).
WORKSPACE_LIB = Path(__file__).resolve().parent / "workspace" / "anim" / "lib"
FONTS_DIR = WORKSPACE_LIB / "fonts"
# Police de la charte (Poppins Black, OFL) ; repli DejaVu si le fichier manque.
_POPPINS = FONTS_DIR / "Poppins-Black.ttf"
FONT_FILE = str(_POPPINS) if _POPPINS.exists() else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp"})

# Planches contact (preview / analyze) : tuiles 9:16 réduites.
TILE_W, TILE_H = 270, 480
SHEET_COLS = 4


def max_ai_images() -> int:
    """Plafond d'images IA par Short (STUDIO_MAX_AI_IMAGES, abaissé par chaîne via le launcher)."""
    return env_int("STUDIO_MAX_AI_IMAGES", 4, minimum=0)
