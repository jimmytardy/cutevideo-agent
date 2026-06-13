from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.channel_config import AiFallbackConfig, resolve_channel_config
from agent.core.cost_estimator import (
    ChannelCostEstimate,
    ai_fallback_from_preview,
    estimate_channel_cost_weekly,
)
from agent.core.database import Channel, get_db
from api.routes.channel_onboarding import _get_channel_or_404

router = APIRouter(prefix="/api/v1/channels", tags=["cost"])


class AiFallbackPreview(BaseModel):
    enabled: bool | None = None
    plan: str | None = None
    fallback_chain: list[str] | None = None
    max_images_per_segment: int | None = None
    max_ai_images_per_video: int | None = None
    max_ai_images_per_week: int | None = None
    fallback_rate_override: float | None = None


class CostEstimatePreviewRequest(BaseModel):
    ai_fallback: AiFallbackPreview = Field(default_factory=AiFallbackPreview)


@router.get("/{channel_id}/cost-estimate", response_model=ChannelCostEstimate)
async def get_channel_cost_estimate(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ChannelCostEstimate:
    channel = await _get_channel_or_404(db, channel_id)
    cfg = resolve_channel_config(channel)
    return estimate_channel_cost_weekly(channel, cfg)


@router.post("/{channel_id}/cost-estimate/preview", response_model=ChannelCostEstimate)
async def preview_channel_cost_estimate(
    channel_id: uuid.UUID,
    body: CostEstimatePreviewRequest,
    db: AsyncSession = Depends(get_db),
) -> ChannelCostEstimate:
    channel = await _get_channel_or_404(db, channel_id)
    cfg = resolve_channel_config(channel)
    override = ai_fallback_from_preview(
        body.ai_fallback.model_dump(exclude_none=True),
        cfg.ai_fallback,
    )
    return estimate_channel_cost_weekly(channel, cfg, ai_override=override)
