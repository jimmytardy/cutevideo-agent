"""Tests estimateur coût images IA."""

from __future__ import annotations

from agent.core.channel_config import AiFallbackConfig, AiImagePlan, resolve_channel_config
from agent.core.cost_estimator import estimate_ai_images_weekly


class _FakeChannel:
    id = "00000000-0000-0000-0000-000000000001"
    theme_category = "animaux"
    config = {
        "production": {"mode": "shorts_only"},
        "publishing": {"daily_quotas": {"long": 0, "short": 3}},
        "media_sources": {
            "ai_fallback": {
                "plan": "flux_schnell",
                "max_images_per_segment": 1,
                "max_ai_images_per_video": 4,
                "fallback_rate_override": 0.45,
            }
        },
    }
    brand_kit = None


def test_estimate_shorts_niche_flux_schnell() -> None:
    channel = _FakeChannel()
    cfg = resolve_channel_config(channel)  # type: ignore[arg-type]
    estimate = estimate_ai_images_weekly(channel, cfg)  # type: ignore[arg-type]
    assert estimate.plan == "flux_schnell"
    assert estimate.provider_family == "flux"
    assert estimate.images_per_week > 0
    assert estimate.cost_eur_per_week < 1.0


def test_estimate_off_plan_zero_cost() -> None:
    channel = _FakeChannel()
    cfg = resolve_channel_config(channel)  # type: ignore[arg-type]
    override = AiFallbackConfig(plan=AiImagePlan.OFF, enabled=False)
    estimate = estimate_ai_images_weekly(channel, cfg, ai_override=override)  # type: ignore[arg-type]
    assert estimate.images_per_week == 0
    assert estimate.cost_eur_per_week == 0.0


def test_imagen3_plan_family() -> None:
    channel = _FakeChannel()
    cfg = resolve_channel_config(channel)  # type: ignore[arg-type]
    override = AiFallbackConfig(plan=AiImagePlan.IMAGEN3)
    estimate = estimate_ai_images_weekly(channel, cfg, ai_override=override)  # type: ignore[arg-type]
    assert estimate.provider_family == "google"
    assert estimate.cost_per_image_eur == 0.037
