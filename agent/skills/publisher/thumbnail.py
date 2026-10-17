from __future__ import annotations

import logging
import uuid
from pathlib import Path

from agent.core.api_keys import fetch_api_key, parse_gcp_credentials
from agent.core.channel_config import AiFallbackConfig
from agent.skills.media_sources.ai.registry import provider_family
from agent.skills.media_sources.ai_image import generate_image

logger = logging.getLogger(__name__)


async def generate_thumbnail(
    title: str,
    theme: str,
    output_dir: Path,
    *,
    ai_cfg: AiFallbackConfig,
    user_id: uuid.UUID | None,
    editorial_tone: str = "",
    aspect_ratio: str = "16:9",
) -> Path | None:
    """Miniature IA de secours (Studio en fournit normalement une), avec le modèle de la chaîne
    et les clés de son propriétaire."""
    if not ai_cfg.enabled or ai_cfg.plan.value == "off":
        return None
    plan = ai_cfg.plan.value
    fal_key = gcp = None
    if provider_family(plan) == "flux":
        fal_key = (await fetch_api_key(user_id, "fal", purpose="thumbnail")).key
    else:
        gcp = parse_gcp_credentials(await fetch_api_key(user_id, "gcp", purpose="thumbnail"))
    tone = editorial_tone or "dramatique, percutant"
    prompt = (
        "Cinematic thumbnail image, no text, no watermark, no logo. "
        f"Topic: {title}. Theme: {theme}. "
        f"Style: {tone}. "
        "High contrast, vivid colors, professional photography or illustration, "
        "eye-catching composition, rule of thirds."
    )
    result = await generate_image(
        prompt,
        output_dir,
        plan=plan,
        aspect_ratio=aspect_ratio,
        fal_api_key=fal_key,
        gcp_credentials=gcp,
    )
    if result:
        return Path(result["local_generated"])
    logger.warning("Génération miniature échouée pour : %s", title[:60])
    return None
