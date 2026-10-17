from __future__ import annotations

import logging

from agent.core.config import load_agent_config
from agent.skills.media_sources.ai.base import ImageGenerationRequest, ImageGenerationResult
from agent.skills.media_sources.ai.flux_common import FluxProvider
from agent.skills.media_sources.ai.imagen3 import Imagen3Provider

logger = logging.getLogger(__name__)

ALLOWED_PLANS = frozenset(
    {"flux_schnell", "flux_pro", "flux_ultra", "flux_2_dev", "imagen3_fast", "imagen3"}
)

_PROVIDERS: dict[str, object] = {
    "flux_schnell": FluxProvider("flux_schnell"),
    "flux_pro": FluxProvider("flux_pro"),
    "flux_ultra": FluxProvider("flux_ultra"),
    "flux_2_dev": FluxProvider("flux_2_dev"),
    "imagen3_fast": Imagen3Provider("imagen3_fast"),
    "imagen3": Imagen3Provider("imagen3"),
}


def provider_family(plan_id: str) -> str:
    if plan_id.startswith("flux_"):
        return "flux"
    if plan_id.startswith("imagen3"):
        return "google"
    return "unknown"


def plan_price_eur(plan_id: str) -> float:
    """Prix d'une image (data/agent_config.json → media_sources.ai_fallback.plan_pricing_eur)."""
    pricing = load_agent_config().get("media_sources", {}).get("ai_fallback", {}).get("plan_pricing_eur", {})
    return float(pricing.get(plan_id, 0.05))


def models_up_to(plan_id: str) -> list[str]:
    """Modèles que Claude peut choisir quand la chaîne est sur `plan_id` : ceux qui ne coûtent
    pas plus cher, `plan_id` en premier (modèle par défaut), puis du moins cher au plus cher."""
    if plan_id not in ALLOWED_PLANS:
        return []
    ceiling = plan_price_eur(plan_id)
    cheaper = sorted(
        (p for p in ALLOWED_PLANS if p != plan_id and plan_price_eur(p) <= ceiling),
        key=lambda p: (plan_price_eur(p), p),
    )
    return [plan_id, *cheaper]


async def generate_with_plan(
    plan_id: str,
    request: ImageGenerationRequest,
) -> ImageGenerationResult | None:
    if plan_id not in ALLOWED_PLANS:
        logger.warning("Plan IA image inconnu : %s", plan_id)
        return None
    provider = _PROVIDERS[plan_id]
    return await provider.generate(request)  # type: ignore[union-attr]
