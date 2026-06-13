from __future__ import annotations

import logging
import uuid
from pathlib import Path

import aiohttp

from agent.core.config import load_agent_config, settings
from agent.skills.media_sources.ai.base import ImageGenerationRequest, ImageGenerationResult
from agent.skills.media_sources.ai.prompt_builder import build_documentary_prompt

logger = logging.getLogger(__name__)

FLUX_ATTRIBUTIONS: dict[str, str] = {
    "flux_schnell": "Image générée par IA (Flux Schnell via fal.ai)",
    "flux_pro": "Image générée par IA (Flux 1.1 Pro via fal.ai)",
    "flux_ultra": "Image générée par IA (Flux 1.1 Pro Ultra via fal.ai)",
}


def _flux_model_for_plan(plan_id: str) -> str | None:
    cfg = load_agent_config().get("media_sources", {}).get("ai_fallback", {}).get("flux", {})
    mapping = {
        "flux_schnell": str(cfg.get("schnell_model", "fal-ai/flux/schnell")),
        "flux_pro": str(cfg.get("pro_model", "fal-ai/flux-pro/v1.1")),
        "flux_ultra": str(cfg.get("ultra_model", "fal-ai/flux-pro/v1.1-ultra")),
    }
    return mapping.get(plan_id)


async def generate_flux_image(
    plan_id: str,
    request: ImageGenerationRequest,
) -> ImageGenerationResult | None:
    if not settings.fal_key:
        logger.warning("FAL_KEY absente — provider Flux %s ignoré", plan_id)
        return None

    model = _flux_model_for_plan(plan_id)
    if not model:
        return None

    full_prompt = build_documentary_prompt(
        request.prompt,
        theme_category=request.theme_category,
        editorial_tone=request.editorial_tone,
        aspect_ratio=request.aspect_ratio,
    )
    payload: dict = {
        "prompt": full_prompt,
        "image_size": {"width": request.image_width, "height": request.image_height},
        "num_images": 1,
        "output_format": "jpeg",
        "safety_tolerance": "2",
    }
    if plan_id == "flux_ultra":
        payload["raw"] = True

    headers = {"Authorization": f"Key {settings.fal_key}", "Content-Type": "application/json"}
    url = f"https://fal.run/{model}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("Flux API error %s (%s): %s", plan_id, resp.status, body[:200])
                    return None
                data = await resp.json()

        images = data.get("images") or []
        if not images:
            return None
        image_url = images[0].get("url")
        if not image_url:
            return None

        request.output_dir.mkdir(parents=True, exist_ok=True)
        dest = request.output_dir / f"ai_{uuid.uuid4().hex[:8]}.jpg"

        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=60)) as img_resp:
                if img_resp.status != 200:
                    return None
                dest.write_bytes(await img_resp.read())

        license_label = str(
            load_agent_config()
            .get("media_sources", {})
            .get("ai_fallback", {})
            .get("license", "synthetic-ai-generated")
        )
        return ImageGenerationResult(
            local_path=dest,
            attribution=FLUX_ATTRIBUTIONS.get(plan_id, f"Image générée par IA (Flux via fal.ai)"),
            license=license_label,
            title=request.prompt[:120],
            provider_plan=plan_id,
        )
    except aiohttp.ClientError as e:
        logger.warning("Génération Flux %s échouée : %s", plan_id, e)
        return None
