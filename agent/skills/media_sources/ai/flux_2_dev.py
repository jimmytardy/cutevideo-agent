from __future__ import annotations

from agent.skills.media_sources.ai.base import ImageGenerationRequest, ImageGenerationResult
from agent.skills.media_sources.ai.flux_common import generate_flux2_image


class Flux2DevProvider:
    plan_id = "flux_2_dev"

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult | None:
        return await generate_flux2_image(self.plan_id, request)
