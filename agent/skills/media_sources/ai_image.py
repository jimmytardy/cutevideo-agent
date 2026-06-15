from __future__ import annotations

import logging
from pathlib import Path

from agent.core.channel_config import AiFallbackConfig
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
    ai_cfg: AiFallbackConfig,
    theme_category: str = "",
    editorial_tone: str = "",
    aspect_ratio: str = "16:9",
    plan_override: str | None = None,
    use_prompt_as_is: bool = False,
    visual_type: str = "",
    fal_api_key: str | None = None,
    gcp_credentials: GcpCredentials | None = None,
) -> dict | None:
    """Génère une image IA en secours via Flux ou Google Imagen 3."""
    if not ai_cfg.enabled or ai_cfg.plan.value == "off":
        return None

    width, height = _dimensions_for_aspect(aspect_ratio)
    request = ImageGenerationRequest(
        prompt=prompt,
        output_dir=output_dir,
        theme_category=theme_category,
        editorial_tone=editorial_tone,
        aspect_ratio=aspect_ratio,
        image_width=width,
        image_height=height,
        visual_type=visual_type,
        use_prompt_as_is=use_prompt_as_is,
        fal_api_key=fal_api_key,
        gcp_credentials=gcp_credentials,
        user_resolved_keys=True,
    )

    if plan_override:
        result = await generate_with_plan(plan_override, request)
        if result:
            return {
                "source": "ai_image",
                "url": None,
                "local_generated": str(result.local_path),
                "license": result.license,
                "attribution": result.attribution,
                "title": result.title,
                "provider_plan": result.provider_plan,
            }
        return None

    chain = ai_cfg.resolved_provider_chain()
    for plan_id in chain[:2]:
        result = await generate_with_plan(plan_id, request)
        if result:
            return {
                "source": "ai_image",
                "url": None,
                "local_generated": str(result.local_path),
                "license": result.license,
                "attribution": result.attribution,
                "title": result.title,
                "provider_plan": result.provider_plan,
            }

    logger.warning("Tous les providers IA ont échoué pour : %s", prompt[:80])
    return None
