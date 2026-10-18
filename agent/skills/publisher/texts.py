"""Texte d'une publication selon la plateforme.

`Publication.description` porte toujours la description YouTube (SEO + hashtags + crédits). TikTok et
Instagram reçoivent la légende écrite pour elles par le miniaturiste dans `publish.json` à la fin de la création
(persistée dans `Project.config.youtube_metadata.tiktok_caption` / `instagram_caption`), sinon un repli court. Résolu à l'exécution : les publications déjà
planifiées et le bouton « Publier » manuel en profitent aussi. Les hashtags sont ajoutés par `build_caption`.
"""

from __future__ import annotations

import uuid

CAPTION_KEYS = {"tiktok": "tiktok_caption", "instagram": "instagram_caption"}


def _without_hashtags_and_credits(description: str) -> str:
    body = description.split("\n\nCrédits :", 1)[0]
    paragraphs = [p for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    return "\n\n".join(paragraphs).strip()


def platform_text(platform: str, title: str, description: str, captions: dict[str, str] | None = None) -> str:
    captions = captions or {}
    if platform == "tiktok":
        return (captions.get("tiktok") or title).strip()
    if platform == "instagram":
        return (captions.get("instagram") or _without_hashtags_and_credits(description) or title).strip()
    return description


async def project_captions(project_id: uuid.UUID | None) -> dict[str, str]:
    """Légendes dédiées du projet (`youtube_metadata`), vides si absentes."""
    if project_id is None:
        return {}
    from agent.core.database import AsyncSessionFactory, Project

    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
    meta = (project.config or {}).get("youtube_metadata") if project and project.config else None
    if not isinstance(meta, dict):
        return {}
    return {platform: str(meta.get(key) or "") for platform, key in CAPTION_KEYS.items()}
