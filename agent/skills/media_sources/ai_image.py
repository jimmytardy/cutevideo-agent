from __future__ import annotations

import logging
from pathlib import Path

from agent.core.api_keys import GcpCredentials
from agent.skills.media_sources.ai.base import ImageGenerationRequest
from agent.skills.media_sources.ai.registry import generate_with_plan

logger = logging.getLogger(__name__)


def _dimensions_for_aspect(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "9:16":
        return 1080, 1920
    return 1920, 1080


async def generate_image(
    prompt: str,
    output_dir: Path,
    *,
    plan: str,
    aspect_ratio: str = "16:9",
    fal_api_key: str | None = None,
    gcp_credentials: GcpCredentials | None = None,
) -> dict | None:
    """Génère une image avec le modèle `plan` (Flux ou Imagen 3), prompt envoyé tel quel."""
    width, height = _dimensions_for_aspect(aspect_ratio)
    request = ImageGenerationRequest(
        prompt=prompt,
        output_dir=output_dir,
        aspect_ratio=aspect_ratio,
        image_width=width,
        image_height=height,
        fal_api_key=fal_api_key,
        gcp_credentials=gcp_credentials,
    )
    result = await generate_with_plan(plan, request)
    if not result:
        logger.warning("Génération IA %s échouée pour : %s", plan, prompt[:80])
        return None
    return {
        "local_generated": str(result.local_path),
        "attribution": result.attribution,
        "provider_plan": result.provider_plan,
    }
