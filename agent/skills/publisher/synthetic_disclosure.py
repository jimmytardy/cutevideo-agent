"""Déclaration « contenu altéré ou synthétique » (YouTube) d'un projet Studio."""

from __future__ import annotations

import uuid
from typing import Any

from agent.core.database import AsyncSessionFactory, Project

AI_IMAGE_SOURCE = "ai_image"


def credits_contain_ai_media(credits: list[dict[str, Any]] | None) -> bool:
    """Vrai si un média effectivement monté vient du générateur d'images IA.

    Les crédits sont ceux du rendu final (`studio/render.py:_used_credits`),
    persistés dans `Project.config.claude_studio.credits`. Les images IA
    Studio (Flux) sont photoréalistes par défaut : on les déclare toujours.
    """
    return any(isinstance(c, dict) and c.get("source") == AI_IMAGE_SOURCE for c in credits or [])


async def detect_realistic_synthetic_media(project_id: uuid.UUID) -> bool:
    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
    if project is None:
        return False
    studio = (project.config or {}).get("claude_studio") or {}
    return credits_contain_ai_media(studio.get("credits"))
