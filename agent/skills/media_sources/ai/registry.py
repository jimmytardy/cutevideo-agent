from __future__ import annotations

import logging

from agent.skills.media_sources.ai.base import ImageGenerationRequest, ImageGenerationResult
from agent.skills.media_sources.ai.flux_pro import FluxProProvider
from agent.skills.media_sources.ai.flux_pro_ultra import FluxUltraProvider
from agent.skills.media_sources.ai.flux_schnell import FluxSchnellProvider
from agent.skills.media_sources.ai.imagen3 import Imagen3Provider

logger = logging.getLogger(__name__)

ALLOWED_PLANS = frozenset(
    {"flux_schnell", "flux_pro", "flux_ultra", "imagen3_fast", "imagen3"}
)

_PROVIDERS: dict[str, object] = {
    "flux_schnell": FluxSchnellProvider(),
    "flux_pro": FluxProProvider(),
    "flux_ultra": FluxUltraProvider(),
    "imagen3_fast": Imagen3Provider("imagen3_fast"),
    "imagen3": Imagen3Provider("imagen3"),
}


def provider_family(plan_id: str) -> str:
    if plan_id.startswith("flux_"):
        return "flux"
    if plan_id.startswith("imagen3"):
        return "google"
    return "unknown"


async def generate_with_plan(
    plan_id: str,
    request: ImageGenerationRequest,
) -> ImageGenerationResult | None:
    if plan_id not in ALLOWED_PLANS:
        logger.warning("Plan IA image inconnu : %s", plan_id)
        return None
    provider = _PROVIDERS[plan_id]
    return await provider.generate(request)  # type: ignore[union-attr]
