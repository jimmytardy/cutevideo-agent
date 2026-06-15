from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status

from agent.core.config import settings

router = APIRouter(prefix="/api/v1/config", tags=["config"])


@router.get("/agent")
async def get_agent_config() -> dict[str, Any]:
    """Retourne la configuration courante des agents."""
    path = Path(settings.config_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@router.put("/agent")
async def update_agent_config(body: dict[str, Any]) -> dict[str, Any]:
    """Met à jour la configuration des agents."""
    path = Path(settings.config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return body


AZURE_VOICES_FR = [
    {
        "id": "fr-FR-Vivienne:DragonHDLatestNeural",
        "label": "Vivienne HD (femme, documentaire) — défaut",
        "styles": ["narration-relaxed", "friendly"],
    },
    {
        "id": "fr-FR-Remy:DragonHDLatestNeural",
        "label": "Remy HD (homme, documentaire)",
        "styles": ["narration-relaxed", "documentary-narration"],
    },
    {"id": "fr-FR-HenriNeural", "label": "Henri (homme)", "styles": ["narration-professional", "newscast-formal"]},
    {"id": "fr-FR-DeniseNeural", "label": "Denise (femme)", "styles": ["cheerful", "friendly", "narration-professional"]},
    {"id": "fr-FR-EloiseNeural", "label": "Eloise (femme)", "styles": ["cheerful", "friendly"]},
    {"id": "fr-FR-VivienneMultilingualNeural", "label": "Vivienne (multilingue)", "styles": ["friendly"]},
]

GEMINI_VOICES = [
    {"id": "Kore", "label": "Kore — ferme, documentaire"},
    {"id": "Charon", "label": "Charon — informatif"},
    {"id": "Aoede", "label": "Aoede — léger"},
    {"id": "Puck", "label": "Puck — dynamique"},
    {"id": "Fenrir", "label": "Fenrir — expressif"},
    {"id": "Leda", "label": "Leda — jeune"},
    {"id": "Orus", "label": "Orus — posé"},
    {"id": "Zephyr", "label": "Zephyr — lumineux"},
]


@router.get("/tts/voices")
async def list_tts_voices() -> list[dict[str, Any]]:
    return AZURE_VOICES_FR


@router.get("/tts/gemini-voices")
async def list_gemini_tts_voices() -> list[dict[str, Any]]:
    return GEMINI_VOICES
