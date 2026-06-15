from __future__ import annotations

import base64
import logging
import uuid
from pathlib import Path

import aiohttp

from agent.core.config import load_agent_config, settings
from agent.skills.media_sources.ai.base import ImageGenerationRequest, ImageGenerationResult
from agent.skills.media_sources.ai.prompt_builder import build_documentary_prompt

logger = logging.getLogger(__name__)

IMAGEN3_ATTRIBUTIONS: dict[str, str] = {
    "imagen3_fast": "Image générée par IA (Google Imagen 3 Fast)",
    "imagen3": "Image générée par IA (Google Imagen 3)",
}


def _model_for_plan(plan_id: str) -> str | None:
    cfg = load_agent_config().get("media_sources", {}).get("ai_fallback", {}).get("imagen3", {})
    mapping = {
        "imagen3_fast": str(cfg.get("fast_model", "imagen-3.0-fast-generate-001")),
        "imagen3": str(cfg.get("standard_model", "imagen-3.0-generate-002")),
    }
    return mapping.get(plan_id)


async def _get_gcp_access_token() -> str | None:
    try:
        import google.auth
        import google.auth.transport.requests

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())
        return str(credentials.token)
    except (ImportError, OSError, ValueError) as e:
        logger.warning("Auth GCP Imagen 3 échouée : %s", e)
        return None


class Imagen3Provider:
    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult | None:
        if not settings.gcp_project_id:
            logger.warning("GCP_PROJECT_ID absent — provider Imagen 3 ignoré")
            return None

        model = _model_for_plan(self.plan_id)
        if not model:
            return None

        token = await _get_gcp_access_token()
        if not token:
            return None

        location = settings.gcp_location
        project = settings.gcp_project_id
        endpoint = (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{location}/publishers/google/models/{model}:predict"
        )

        full_prompt = (
            request.prompt
            if request.use_prompt_as_is
            else build_documentary_prompt(
                request.prompt,
                theme_category=request.theme_category,
                editorial_tone=request.editorial_tone,
                aspect_ratio=request.aspect_ratio,
            )
        )
        aspect = "9:16" if request.aspect_ratio == "9:16" else "16:9"

        payload = {
            "instances": [{"prompt": full_prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": aspect,
                "personGeneration": "allow_adult",
                "safetySetting": "block_medium_and_above",
            },
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "Imagen 3 API error %s (%s): %s",
                            self.plan_id,
                            resp.status,
                            body[:200],
                        )
                        return None
                    data = await resp.json()

            predictions = data.get("predictions") or []
            if not predictions:
                return None
            encoded = predictions[0].get("bytesBase64Encoded")
            if not encoded:
                return None

            request.output_dir.mkdir(parents=True, exist_ok=True)
            dest = request.output_dir / f"ai_{uuid.uuid4().hex[:8]}.jpg"
            dest.write_bytes(base64.b64decode(encoded))

            license_label = str(
                load_agent_config()
                .get("media_sources", {})
                .get("ai_fallback", {})
                .get("license", "synthetic-ai-generated")
            )
            return ImageGenerationResult(
                local_path=dest,
                attribution=IMAGEN3_ATTRIBUTIONS.get(
                    self.plan_id, "Image générée par IA (Google Imagen 3)"
                ),
                license=license_label,
                title=request.prompt[:120],
                provider_plan=self.plan_id,
            )
        except aiohttp.ClientError as e:
            logger.warning("Génération Imagen 3 %s échouée : %s", self.plan_id, e)
            return None
