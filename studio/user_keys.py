"""Clés de l'utilisateur transmises par le launcher aux outils Studio.

Le launcher retire de l'environnement hérité toute clé de plateforme (`INHERITED_SECRET_VARS`)
puis pose celles du propriétaire de la chaîne dans les variables `STUDIO_*` ci-dessous : les
outils (`python -m studio.tools`) ne lisent que celles-ci, jamais `.env` ni `settings`.
Le bac à sable des animations démarre avec un environnement vide (`--clearenv`).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.api_keys import UserKeys

GEMINI_API_KEY = "STUDIO_GEMINI_API_KEY"
FAL_KEY = "STUDIO_FAL_KEY"
AZURE_SPEECH_KEY = "STUDIO_AZURE_SPEECH_KEY"
AZURE_SPEECH_REGION = "STUDIO_AZURE_SPEECH_REGION"
GCP_CREDENTIALS_JSON = "STUDIO_GCP_CREDENTIALS_JSON"

STUDIO_SECRET_VARS = (GEMINI_API_KEY, FAL_KEY, AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, GCP_CREDENTIALS_JSON)

# Variables qu'un ancien `.env` ou l'hôte pourraient encore exposer : jamais transmises au CLI.
INHERITED_SECRET_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GOOGLE_GEMINI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "FAL_KEY",
    "AZURE_SPEECH_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GCP_PROJECT_ID",
    "YOUTUBE_REFRESH_TOKEN",
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_PAGE_ID",
    *STUDIO_SECRET_VARS,
)


def studio_env(keys: UserKeys) -> dict[str, str]:
    """Variables à poser pour le CLI (`ANTHROPIC_API_KEY`) et ses outils (`STUDIO_*`)."""
    values = {
        "ANTHROPIC_API_KEY": keys.anthropic,
        GEMINI_API_KEY: keys.gemini,
        FAL_KEY: keys.fal,
        AZURE_SPEECH_KEY: keys.azure_speech,
        AZURE_SPEECH_REGION: keys.azure_speech_region,
        GCP_CREDENTIALS_JSON: keys.gcp_credentials_json,
    }
    return {name: value for name, value in values.items() if value}


def user_key(name: str) -> str | None:
    """Clé posée par le launcher pour ce run (None si l'utilisateur n'en a pas)."""
    return (os.getenv(name) or "").strip() or None
