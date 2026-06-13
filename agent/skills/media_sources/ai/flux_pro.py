from __future__ import annotations

from agent.skills.media_sources.ai.base import ImageGenerationRequest, ImageGenerationResult
from agent.skills.media_sources.ai.flux_common import generate_flux_image


class FluxProProvider:
    plan_id = "flux_pro"

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult | None:
        return await generate_flux_image(self.plan_id, request)
