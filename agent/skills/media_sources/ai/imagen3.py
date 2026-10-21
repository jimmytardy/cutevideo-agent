from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import TYPE_CHECKING

from agent.skills.media_sources.ai.base import (
    ImageBilledButLost,
    ImageGenerationRequest,
    ImageGenerationResult,
    ai_fallback_config,
    ai_license_label,
    post_generation,
)

if TYPE_CHECKING:
    from agent.core.api_keys import GcpCredentials

logger = logging.getLogger(__name__)

IMAGEN3_ATTRIBUTIONS: dict[str, str] = {
    "imagen3_fast": "Image générée par IA (Google Imagen 3 Fast)",
    "imagen3": "Image générée par IA (Google Imagen 3)",
}


def _model_for_plan(plan_id: str) -> str | None:
    cfg = ai_fallback_config().get("imagen3", {})
    mapping = {
        "imagen3_fast": str(cfg.get("fast_model", "imagen-3.0-fast-generate-001")),
        "imagen3": str(cfg.get("standard_model", "imagen-3.0-generate-002")),
    }
    return mapping.get(plan_id)


async def _get_gcp_access_token(
    gcp_credentials: GcpCredentials | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Retourne (token, project_id, location)."""
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError as e:
        logger.warning("Auth GCP Imagen 3 échouée : %s", e)
        return None, None, None

    if gcp_credentials and gcp_credentials.credentials_json:
        try:
            from google.oauth2 import service_account

            info = json.loads(gcp_credentials.credentials_json)
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            credentials.refresh(google.auth.transport.requests.Request())
            return (
                str(credentials.token),
                gcp_credentials.project_id,
                gcp_credentials.location,
            )
        except (ValueError, OSError, KeyError) as e:
            logger.warning("Auth GCP Imagen 3 (compte user) échouée : %s", e)
            return None, None, None

    return None, None, None


class Imagen3Provider:
    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult | None:
        plan_id = self.plan_id
        gcp = request.gcp_credentials
        if gcp is None:
            logger.warning("Credentials GCP de l'utilisateur absents — provider Imagen 3 ignoré")
            return None

        model = _model_for_plan(plan_id)
        if not model:
            return None

        token, project, location = await _get_gcp_access_token(gcp)
        if not token or not project or not location:
            return None

        endpoint = (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{location}/publishers/google/models/{model}:predict"
        )

        payload = {
            "instances": [{"prompt": request.prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "9:16" if request.aspect_ratio == "9:16" else "16:9",
                "personGeneration": "allow_adult",
                "safetySetting": "block_medium_and_above",
            },
        }

        # Le code 200 de Vertex est la frontière de facturation ; `post_generation` classe les échecs
        # de part et d'autre (`None` = rien à payer, `ImageBilledButLost` = image payée puis perdue).
        data = await post_generation(
            endpoint,
            payload=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            output_dir=request.output_dir,
            provider="Imagen 3",
            plan_id=plan_id,
            log=logger,
        )
        if data is None:
            return None

        # Un 200 sans aucune prédiction est la façon dont Vertex signale une sortie écartée par ses
        # filtres de sécurité : la génération n'a pas eu lieu, donc on ne consomme pas le plafond.
        predictions = data.get("predictions") or []
        if not predictions:
            logger.warning("Imagen 3 %s : réponse sans prédiction (prompt probablement filtré)", plan_id)
            return None

        # Au-delà, l'image existe et a été facturée : un échec de décodage ou d'écriture est une image
        # perdue, qui doit compter.
        try:
            encoded = predictions[0].get("bytesBase64Encoded")
            if not encoded:
                raise ImageBilledButLost(f"{plan_id} : prédiction sans image")
            dest = request.output_dir / f"ai_{uuid.uuid4().hex[:8]}.jpg"
            dest.write_bytes(base64.b64decode(encoded))
        except (ValueError, OSError, AttributeError, TypeError, KeyError, IndexError) as e:
            raise ImageBilledButLost(f"{plan_id} : image perdue après facturation ({e})") from e

        return ImageGenerationResult(
            local_path=dest,
            attribution=IMAGEN3_ATTRIBUTIONS.get(plan_id, "Image générée par IA (Google Imagen 3)"),
            license=ai_license_label(),
            title=request.prompt[:120],
            provider_plan=plan_id,
        )
