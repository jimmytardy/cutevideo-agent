"""Lecture tolérante des variables d'environnement numériques.

Une valeur absente, vide ou invalide retombe sur le défaut (avec un avertissement
pour une valeur invalide) au lieu de lever une exception — y compris à l'import.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        logger.warning("%s=%r invalide (entier attendu) — défaut %s", name, raw, default)
        value = default
    return value if minimum is None else max(minimum, value)


def env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        logger.warning("%s=%r invalide (nombre attendu) — défaut %s", name, raw, default)
        value = default
    return value if minimum is None else max(minimum, value)


def env_optional_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r invalide (nombre attendu) — ignoré", name, raw)
        return None
