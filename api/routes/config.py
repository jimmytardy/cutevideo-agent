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
