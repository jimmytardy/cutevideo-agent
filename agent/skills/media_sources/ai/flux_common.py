from __future__ import annotations

import logging
import uuid

import aiohttp

from agent.skills.media_sources.ai.base import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ai_fallback_config,
    ai_license_label,
)

logger = logging.getLogger(__name__)

FLUX_ATTRIBUTIONS: dict[str, str] = {
    "flux_schnell": "Image générée par IA (Flux Schnell via fal.ai)",
    "flux_pro": "Image générée par IA (Flux 1.1 Pro via fal.ai)",
    "flux_ultra": "Image générée par IA (Flux 1.1 Pro Ultra via fal.ai)",
    "flux_2_dev": "Image générée par IA (FLUX 2 Dev via fal.ai)",
}


def _flux_model_for_plan(plan_id: str) -> str | None:
    cfg = ai_fallback_config().get("flux", {})
    mapping = {
        "flux_schnell": str(cfg.get("schnell_model", "fal-ai/flux/schnell")),
        "flux_pro": str(cfg.get("pro_model", "fal-ai/flux-pro/v1.1")),
        "flux_ultra": str(cfg.get("ultra_model", "fal-ai/flux-pro/v1.1-ultra")),
        "flux_2_dev": str(cfg.get("dev_model", "fal-ai/flux-2")),
    }
    return mapping.get(plan_id)


def _payload(plan_id: str, request: ImageGenerationRequest) -> dict:
    payload: dict = {
        "prompt": request.prompt,
        "image_size": {"width": request.image_width, "height": request.image_height},
        "num_images": 1,
        "output_format": "jpeg",
    }
    if plan_id == "flux_2_dev":
        payload.update(enable_safety_checker=True, guidance_scale=2.5)
    else:
        payload["safety_tolerance"] = "2"
    if plan_id == "flux_ultra":
        payload["raw"] = True
    return payload


class FluxProvider:
    """Modèles Flux de fal.ai, avec la clé fal du propriétaire de la chaîne (aucune clé plateforme)."""

    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult | None:
        plan_id = self.plan_id
        fal_key = request.fal_api_key
        if not fal_key:
            logger.warning("Clé fal absente — provider Flux %s ignoré", plan_id)
            return None
        model = _flux_model_for_plan(plan_id)
        if not model:
            return None

        headers = {"Authorization": f"Key {fal_key}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"https://fal.run/{model}",
                    headers=headers,
                    json=_payload(plan_id, request),
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning("Flux API error %s (%s): %s", plan_id, resp.status, body[:200])
                        return None
                    data = await resp.json()

            images = data.get("images") or []
            image_url = images[0].get("url") if images else None
            if not image_url:
                return None

            request.output_dir.mkdir(parents=True, exist_ok=True)
            dest = request.output_dir / f"ai_{uuid.uuid4().hex[:8]}.jpg"
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=60)) as img_resp:
                    if img_resp.status != 200:
                        return None
                    dest.write_bytes(await img_resp.read())

            return ImageGenerationResult(
                local_path=dest,
                attribution=FLUX_ATTRIBUTIONS.get(plan_id, "Image générée par IA (Flux via fal.ai)"),
                license=ai_license_label(),
                title=request.prompt[:120],
                provider_plan=plan_id,
            )
        except aiohttp.ClientError as e:
            logger.warning("Génération Flux %s échouée : %s", plan_id, e)
            return None
