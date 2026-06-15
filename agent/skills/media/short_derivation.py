from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent.core.database import MediaAsset, Scenario
from agent.core.short_derivation import DerivedShortPlan, derivation_iteration

if TYPE_CHECKING:
    from agent.agents.media_agent import MediaAgent
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)


async def run_media_for_short_derivation(
    agent: "MediaAgent",
    ctx: "PipelineContext",
    plan: DerivedShortPlan,
) -> list[MediaAsset]:
    """Recherche média pour un short dérivé : pool d'abord, sources gratuites, IA optionnelle."""
    ctx.derivation_short_index = plan.index
    if ctx.short_derivation_mode is None:
        ctx.short_derivation_mode = ctx.channel_config.short_derivation.mode

    scenario = Scenario(
        project_id=ctx.project_id,
        segments=plan.segments,
        total_duration_s=plan.total_duration_s,
        iteration=derivation_iteration(plan.index),
    )
    return await agent._search_all_segments_derivation(ctx, scenario)
