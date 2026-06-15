from __future__ import annotations

import logging
from pathlib import Path

from agent.core.channel_config import AiFallbackConfig
from agent.skills.media_sources.ai_image import generate_image

logger = logging.getLogger(__name__)


async def generate_thumbnail(
    title: str,
    theme: str,
    output_dir: Path,
    ai_cfg: AiFallbackConfig,
    editorial_tone: str = "",
    aspect_ratio: str = "16:9",
) -> Path | None:
    """Génère une image de miniature via IA (Flux ou Imagen3)."""
    tone = editorial_tone or "dramatique, percutant"
    prompt = (
        "Cinematic thumbnail image, no text, no watermark, no logo. "
        f"Topic: {title}. Theme: {theme}. "
        f"Style: {tone}. "
        "High contrast, vivid colors, professional photography or illustration, "
        "eye-catching composition, rule of thirds."
    )
    result = await generate_image(
        prompt=prompt,
        output_dir=output_dir,
        ai_cfg=ai_cfg,
        theme_category=theme,
        editorial_tone=tone,
        aspect_ratio=aspect_ratio,
    )
    if result:
        return Path(result["local_generated"])
    logger.warning("Génération miniature échouée pour : %s", title[:60])
    return None
