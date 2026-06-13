from __future__ import annotations

from agent.skills.media_sources.ai.base import ImageGenerationRequest, ImageGenerationResult
from agent.skills.media_sources.ai.flux_common import generate_flux_image


class FluxSchnellProvider:
    plan_id = "flux_schnell"

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult | None:
        return await generate_flux_image(self.plan_id, request)
