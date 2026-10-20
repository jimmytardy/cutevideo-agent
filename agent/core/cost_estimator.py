from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agent.core.channel_config import AiFallbackConfig, AiImagePlan, ChannelRuntimeConfig
from agent.core.database import Channel
from agent.skills.media_sources.ai.registry import plan_price_eur, provider_family


class AiCostEstimate(BaseModel):
    """Borne haute : chaque vidéo utilise tout son plafond d'images IA, au prix du modèle de la chaîne
    (Claude peut choisir un modèle moins cher, ou ne générer aucune image)."""

    plan: str
    plan_label: str
    provider_family: str
    cost_per_image_eur: float
    videos_per_week: float
    max_ai_images_per_video: int
    images_per_week: int
    cost_eur_per_week: float
    cost_eur_per_month: float


class TtsCostEstimate(BaseModel):
    cost_eur_per_week: float = 0.0
    note: str = "Estimation TTS non calculée dans cette version"


class ChannelCostEstimate(BaseModel):
    channel_id: str
    period: str = "week"
    ai_images: AiCostEstimate
    tts: TtsCostEstimate
    total_eur_per_week: float


PLAN_LABELS: dict[str, str] = {
    "off": "Désactivé",
    "flux_schnell": "Flux Schnell",
    "flux_2_dev": "FLUX 2 Dev",
    "flux_pro": "FLUX.2 Pro",
    "flux_ultra": "Flux Pro Ultra",
    "imagen3_fast": "Imagen 3 Fast",
    "imagen3": "Imagen 3",
}


def _videos_per_week(cfg: ChannelRuntimeConfig) -> float:
    quotas = cfg.daily_quotas
    if cfg.production_mode == "long_only":
        return quotas.long * 7
    if cfg.production_mode == "shorts_only":
        return quotas.short * 7
    return (quotas.long + quotas.short) * 7


def estimate_ai_images_weekly(
    cfg: ChannelRuntimeConfig,
    *,
    ai_override: AiFallbackConfig | None = None,
) -> AiCostEstimate:
    ai_cfg = ai_override or cfg.ai_fallback
    plan_id = ai_cfg.plan.value
    if plan_id == "off" or not ai_cfg.enabled:
        return AiCostEstimate(
            plan="off",
            plan_label=PLAN_LABELS["off"],
            provider_family="none",
            cost_per_image_eur=0.0,
            videos_per_week=0.0,
            max_ai_images_per_video=0,
            images_per_week=0,
            cost_eur_per_week=0.0,
            cost_eur_per_month=0.0,
        )

    videos_week = _videos_per_week(cfg)
    images_week = max(0, round(videos_week * ai_cfg.max_ai_images_per_video))
    cost_per_image = plan_price_eur(plan_id)
    cost_week = round(images_week * cost_per_image, 2)
    return AiCostEstimate(
        plan=plan_id,
        plan_label=PLAN_LABELS.get(plan_id, plan_id),
        provider_family=provider_family(plan_id),
        cost_per_image_eur=cost_per_image,
        videos_per_week=round(videos_week, 1),
        max_ai_images_per_video=ai_cfg.max_ai_images_per_video,
        images_per_week=images_week,
        cost_eur_per_week=cost_week,
        cost_eur_per_month=round(cost_week * 4.33, 2),
    )


def estimate_channel_cost_weekly(
    channel: Channel,
    cfg: ChannelRuntimeConfig,
    *,
    ai_override: AiFallbackConfig | None = None,
) -> ChannelCostEstimate:
    ai = estimate_ai_images_weekly(cfg, ai_override=ai_override)
    return ChannelCostEstimate(
        channel_id=str(channel.id),
        ai_images=ai,
        tts=TtsCostEstimate(),
        total_eur_per_week=ai.cost_eur_per_week,
    )


def ai_fallback_from_preview(body: dict[str, Any], base: AiFallbackConfig) -> AiFallbackConfig:
    data = {**base.model_dump(), **body}
    if "plan" in data:
        try:
            data["plan"] = AiImagePlan(str(data["plan"]))
        except ValueError:
            data["plan"] = base.plan
    return AiFallbackConfig.model_validate(data)
