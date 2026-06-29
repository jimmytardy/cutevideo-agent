from __future__ import annotations

import uuid

from sqlalchemy import select

from agent.core.database import AsyncSessionFactory, MediaAsset

_PHOTOREALISTIC_VISUAL_TYPES = frozenset({
    "documentary_photo",
    "portrait_photo",
    "news_broll",
    "archival_footage",
    "historical_photo",
    "landscape_photo",
    "wildlife_photo",
    "sports_action",
    "wildlife_action",
})


def is_photorealistic_ai_asset(asset: MediaAsset) -> bool:
    """True si asset IA sélectionné avec rendu photoréaliste."""
    if (asset.source or "").lower() != "ai":
        return False
    if not asset.selected:
        return False
    vtype = (asset.visual_type or "").lower().strip()
    if vtype in _PHOTOREALISTIC_VISUAL_TYPES:
        return True
    license_tag = (asset.license or "").lower()
    return "synthetic" in license_tag and vtype not in (
        "diagram",
        "animated_text",
        "infographic",
        "chart",
        "meme",
        "illustration",
    )


async def detect_realistic_synthetic_media(project_id: uuid.UUID) -> bool:
    """Au moins un média IA photoréaliste sélectionné dans le projet."""
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MediaAsset).where(
                MediaAsset.project_id == project_id,
                MediaAsset.selected == True,  # noqa: E712
            )
        )
        assets = list(result.scalars().all())
    return any(is_photorealistic_ai_asset(a) for a in assets)
