from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent.core.channel_config import AiFallbackConfig, AiImagePlan, ChannelRuntimeConfig
from agent.core.config import load_agent_config
from agent.core.database import Channel
from agent.skills.media_sources.ai.registry import provider_family


class AiCostBreakdown(BaseModel):
    theme_category: str
    fallback_rate: float
    videos_per_week: float
    segments_per_week: float
    max_images_per_segment: int
    max_ai_images_per_video: int
    max_ai_images_per_week: int | None
    raw_images_before_caps: float
    images_per_week: int
    plan: str
    plan_label: str
    provider_family: str
    cost_per_image_eur: float


class AiCostEstimate(BaseModel):
    plan: str
    plan_label: str
    provider_family: str
    cost_per_image_eur: float
    images_per_week: int
    cost_eur_per_week: float
    cost_eur_per_month: float
    breakdown: AiCostBreakdown


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
    "flux_pro": "Flux 1.1 Pro",
    "flux_ultra": "Flux Pro Ultra",
    "imagen3_fast": "Imagen 3 Fast",
    "imagen3": "Imagen 3",
}


def _plan_pricing_eur() -> dict[str, float]:
    cfg = load_agent_config().get("media_sources", {}).get("ai_fallback", {})
    defaults = {
        "flux_schnell": 0.003,
        "flux_pro": 0.05,
        "flux_ultra": 0.07,
        "imagen3_fast": 0.018,
        "imagen3": 0.037,
    }
    raw = cfg.get("plan_pricing_eur", {})
    return {**defaults, **{str(k): float(v) for k, v in raw.items()}}


def _niche_fallback_rates() -> dict[str, float]:
    cfg = load_agent_config().get("media_sources", {}).get("niche_fallback_rates", {})
    defaults = {
        "histoire": 0.05,
        "france": 0.05,
        "science": 0.12,
        "nature": 0.10,
        "animaux": 0.15,
        "art": 0.20,
        "default": 0.25,
    }
    return {**defaults, **{str(k): float(v) for k, v in cfg.items()}}


def _fallback_rate_for_category(theme_category: str, ai_cfg: AiFallbackConfig) -> float:
    if ai_cfg.fallback_rate_override is not None:
        return ai_cfg.fallback_rate_override
    category = theme_category.lower()
    rates = _niche_fallback_rates()
    for key, rate in rates.items():
        if key != "default" and key in category:
            return rate
    return rates.get("default", 0.25)


def _videos_per_week(cfg: ChannelRuntimeConfig) -> float:
    quotas = cfg.daily_quotas
    if cfg.production_mode == "long_only":
        return quotas.long * 7
    if cfg.production_mode == "shorts_only":
        return quotas.short * 7
    return (quotas.long + quotas.short) * 7


def _segments_per_video(cfg: ChannelRuntimeConfig) -> float:
    if cfg.production_mode == "shorts_only":
        return 2.0
    if cfg.production_mode == "long_only":
        return 12.0
    long_count = max(cfg.daily_quotas.long, 0)
    short_count = max(cfg.daily_quotas.short, 0)
    total_videos = long_count + short_count
    if total_videos <= 0:
        return 4.5
    return (long_count * 12 + short_count * 2) / total_videos


def estimate_ai_images_weekly(
    channel: Channel,
    cfg: ChannelRuntimeConfig,
    *,
    ai_override: AiFallbackConfig | None = None,
) -> AiCostEstimate:
    ai_cfg = ai_override or cfg.ai_fallback
    plan_id = ai_cfg.plan.value
    pricing = _plan_pricing_eur()

    if plan_id == "off" or not ai_cfg.enabled:
        breakdown = AiCostBreakdown(
            theme_category=channel.theme_category,
            fallback_rate=0.0,
            videos_per_week=0.0,
            segments_per_week=0.0,
            max_images_per_segment=ai_cfg.max_images_per_segment,
            max_ai_images_per_video=ai_cfg.max_ai_images_per_video,
            max_ai_images_per_week=ai_cfg.max_ai_images_per_week,
            raw_images_before_caps=0.0,
            images_per_week=0,
            plan="off",
            plan_label=PLAN_LABELS["off"],
            provider_family="none",
            cost_per_image_eur=0.0,
        )
        return AiCostEstimate(
            plan="off",
            plan_label=PLAN_LABELS["off"],
            provider_family="none",
            cost_per_image_eur=0.0,
            images_per_week=0,
            cost_eur_per_week=0.0,
            cost_eur_per_month=0.0,
            breakdown=breakdown,
        )

    videos_week = _videos_per_week(cfg)
    segments_per_video = _segments_per_video(cfg)
    segments_week = videos_week * segments_per_video
    fallback_rate = _fallback_rate_for_category(channel.theme_category, ai_cfg)
    segments_needing_ai = segments_week * fallback_rate
    raw_images = segments_needing_ai * ai_cfg.max_images_per_segment
    capped_by_video = videos_week * ai_cfg.max_ai_images_per_video
    images_week = min(raw_images, capped_by_video)
    if ai_cfg.max_ai_images_per_week is not None:
        images_week = min(images_week, ai_cfg.max_ai_images_per_week)
    images_week_int = max(0, round(images_week))

    cost_per_image = pricing.get(plan_id, 0.0)
    cost_week = round(images_week_int * cost_per_image, 2)

    breakdown = AiCostBreakdown(
        theme_category=channel.theme_category,
        fallback_rate=round(fallback_rate, 3),
        videos_per_week=round(videos_week, 1),
        segments_per_week=round(segments_week, 1),
        max_images_per_segment=ai_cfg.max_images_per_segment,
        max_ai_images_per_video=ai_cfg.max_ai_images_per_video,
        max_ai_images_per_week=ai_cfg.max_ai_images_per_week,
        raw_images_before_caps=round(raw_images, 1),
        images_per_week=images_week_int,
        plan=plan_id,
        plan_label=PLAN_LABELS.get(plan_id, plan_id),
        provider_family=provider_family(plan_id),
        cost_per_image_eur=cost_per_image,
    )
    return AiCostEstimate(
        plan=plan_id,
        plan_label=PLAN_LABELS.get(plan_id, plan_id),
        provider_family=provider_family(plan_id),
        cost_per_image_eur=cost_per_image,
        images_per_week=images_week_int,
        cost_eur_per_week=cost_week,
        cost_eur_per_month=round(cost_week * 4.33, 2),
        breakdown=breakdown,
    )


def estimate_channel_cost_weekly(
    channel: Channel,
    cfg: ChannelRuntimeConfig,
    *,
    ai_override: AiFallbackConfig | None = None,
) -> ChannelCostEstimate:
    ai = estimate_ai_images_weekly(channel, cfg, ai_override=ai_override)
    tts = TtsCostEstimate()
    return ChannelCostEstimate(
        channel_id=str(channel.id),
        ai_images=ai,
        tts=tts,
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
