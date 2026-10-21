from __future__ import annotations

import logging
import uuid
from typing import Any

import aiohttp

from agent.skills.media_sources.ai.base import (
    ImageBilledButLost,
    ImageGenerationRequest,
    ImageGenerationResult,
    ai_fallback_config,
    ai_license_label,
    post_generation,
)

logger = logging.getLogger(__name__)

FLUX_ATTRIBUTIONS: dict[str, str] = {
    "flux_schnell": "Image générée par IA (Flux Schnell via fal.ai)",
    "flux_pro": "Image générée par IA (FLUX.2 Pro via fal.ai)",
    "flux_ultra": "Image générée par IA (Flux 1.1 Pro Ultra via fal.ai)",
    "flux_2_dev": "Image générée par IA (FLUX 2 Dev via fal.ai)",
}


def _flux_model_for_plan(plan_id: str) -> str | None:
    cfg = ai_fallback_config().get("flux", {})
    mapping = {
        "flux_schnell": str(cfg.get("schnell_model", "fal-ai/flux/schnell")),
        "flux_pro": str(cfg.get("pro_model", "fal-ai/flux-2-pro")),
        "flux_ultra": str(cfg.get("ultra_model", "fal-ai/flux-pro/v1.1-ultra")),
        "flux_2_dev": str(cfg.get("dev_model", "fal-ai/flux-2")),
    }
    return mapping.get(plan_id)


# Paramètres propres à chaque endpoint, d'après les schémas publiés par fal. Aucun n'accepte exactement
# les mêmes champs, et fal **ignore en silence** ceux qu'il ne connaît pas (vérifié : un champ inventé ne
# lève rien) — un paramètre envoyé au mauvais endpoint est donc un réglage perdu sans la moindre erreur.
# Une table par modèle, et non un branchement par famille ou par id de plan : changer le modèle d'un plan
# dans `data/agent_config.json` lui donne ainsi d'emblée les bons paramètres.
_FLUX_EXTRAS: dict[str, dict[str, Any]] = {
    "fal-ai/flux/schnell": {"enable_safety_checker": True},
    "fal-ai/flux-2": {"enable_safety_checker": True, "guidance_scale": 2.5},
    "fal-ai/flux-2-pro": {"enable_safety_checker": True, "safety_tolerance": "2"},
    "fal-ai/flux-pro/v1.1": {"safety_tolerance": "2"},
    "fal-ai/flux-pro/v1.1-ultra": {"safety_tolerance": "2", "raw": True},
}
# Endpoints dimensionnés par `aspect_ratio` et non par `image_size`. L'ultra est dans ce cas et son défaut
# est `16:9` : sans ce traitement, un Short vertical revenait en paysage, puis était rogné au montage.
_ASPECT_RATIO_MODELS = frozenset({"fal-ai/flux-pro/v1.1-ultra"})


def _payload(model: str, request: ImageGenerationRequest) -> dict:
    """Charge utile d'un modèle Flux, dérivée du **modèle** et de son schéma (cf. `_FLUX_EXTRAS`).

    `num_images` n'est pas envoyé : son défaut vaut 1 partout où il existe, et il est absent du schéma de
    `flux-2-pro`. `output_format` l'est en revanche, car le défaut du dev est `png`.
    """
    payload: dict[str, Any] = {"prompt": request.prompt, "output_format": "jpeg"}
    if model in _ASPECT_RATIO_MODELS:
        payload["aspect_ratio"] = request.aspect_ratio
    else:
        payload["image_size"] = {"width": request.image_width, "height": request.image_height}
    # Modèle inconnu (config modifiée à chaud) : rien de plus, plutôt qu'un champ peut-être non supporté.
    payload.update(_FLUX_EXTRAS.get(model, {}))
    return payload


class FluxProvider:
    """Modèles Flux de fal.ai, avec la clé fal du propriétaire de la chaîne (aucune clé plateforme)."""

    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult | None:
        plan_id = self.plan_id
        fal_key = request.fal_api_key
        if not fal_key:
            logger.warning("Clé fal absente — provider Flux %s ignoré", plan_id)
            return None
        model = _flux_model_for_plan(plan_id)
        if not model:
            return None

        # Le code 200 de `fal.run` est la frontière de facturation ; `post_generation` classe les échecs
        # de part et d'autre (`None` = rien à payer, `ImageBilledButLost` = image payée puis perdue).
        data = await post_generation(
            f"https://fal.run/{model}",
            payload=_payload(model, request),
            headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
            output_dir=request.output_dir,
            provider="Flux",
            plan_id=plan_id,
            log=logger,
        )
        if data is None:
            return None

        # Passé le 200, l'image est produite et payée : tout échec de récupération est une image perdue.
        try:
            images = data.get("images") or []
            image_url = images[0].get("url") if images else None
            if not image_url:
                raise ImageBilledButLost(f"{plan_id} : réponse sans image")
            dest = request.output_dir / f"ai_{uuid.uuid4().hex[:8]}.jpg"
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=60)) as img_resp:
                    if img_resp.status != 200:
                        raise ImageBilledButLost(f"{plan_id} : téléchargement en {img_resp.status}")
                    dest.write_bytes(await img_resp.read())
        except (aiohttp.ClientError, TimeoutError, OSError, AttributeError, TypeError, IndexError, KeyError) as e:
            raise ImageBilledButLost(f"{plan_id} : image perdue après facturation ({e})") from e

        return ImageGenerationResult(
            local_path=dest,
            attribution=FLUX_ATTRIBUTIONS.get(plan_id, "Image générée par IA (Flux via fal.ai)"),
            license=ai_license_label(),
            title=request.prompt[:120],
            provider_plan=plan_id,
        )
