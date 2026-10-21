from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from agent.core.api_keys import GcpCredentials
from agent.core.config import load_agent_config


@dataclass(frozen=True)
class ImageGenerationRequest:
    # Prompt envoyé tel quel au modèle (écrit par Claude, cf. studio/workspace/docs/ai-images.md).
    prompt: str
    output_dir: Path
    aspect_ratio: str = "16:9"
    image_width: int = 1920
    image_height: int = 1080
    fal_api_key: str | None = None
    gcp_credentials: GcpCredentials | None = None


@dataclass(frozen=True)
class ImageGenerationResult:
    local_path: Path
    attribution: str
    license: str
    title: str
    provider_plan: str


async def error_body(resp: aiohttp.ClientResponse) -> str:
    """Corps d'une réponse d'erreur, pour le journal. Ne lève jamais.

    Lire ce corps est un confort de diagnostic : un corps binaire (page de passerelle) ou une lecture
    qui expire ne doit pas se transformer en exception, qui ferait passer un refus — gratuit — pour
    une panne inclassable.
    """
    try:
        return (await resp.text())[:200]
    except Exception as exc:  # noqa: BLE001 — diagnostic seulement
        return f"<corps illisible : {exc}>"


class ImageBilledButLost(RuntimeError):
    """Le fournisseur a accepté la requête — donc facturé — mais l'image n'a pas pu être récupérée.

    À distinguer d'un `None`, qui dit « refusé, rien à payer ». Sans cette distinction, l'appelant ne
    compterait pas une génération payée et un rôle pourrait réessayer en boucle aux frais du propriétaire
    de la chaîne.
    """


async def post_generation(
    url: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str],
    output_dir: Path,
    provider: str,
    plan_id: str,
    log: logging.Logger,
) -> dict[str, Any] | None:
    """Appel de génération : rend le JSON d'une réponse 200, ou `None` si rien n'a été facturé.

    La frontière de facturation est le **code 200**. En deçà, le fournisseur n'a rien produit et
    l'échec est gratuit : `None`, et l'appelant rend sa réservation. Au-delà, l'image a été produite
    et payée, donc tout échec est une image *perdue* (`ImageBilledButLost`, comptée par l'appelant) et
    jamais une génération gratuite. Les deux fournisseurs passent par ici pour que ce classement — qui
    décide d'une dépense réelle — n'existe qu'en un seul endroit ; seuls les messages les distinguent.
    """
    # Avant de payer : si le dossier de sortie est inécrivable, autant le savoir gratuitement.
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("Génération %s %s impossible (dossier de sortie) : %s", provider, plan_id, e)
        return None

    data = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120, sock_connect=15),
            ) as resp:
                if resp.status != 200:
                    body = await error_body(resp)
                    log.warning("%s API error %s (%s): %s", provider, plan_id, resp.status, body)
                    return None
                try:
                    data = await resp.json()
                except (aiohttp.ClientError, ValueError, TimeoutError) as e:
                    raise ImageBilledButLost(f"{plan_id} : réponse illisible ({e})") from e
                if not isinstance(data, dict):
                    # `None` est réservé au « rien à payer » : un corps 200 qui n'est pas un objet est
                    # une image facturée dont on ne saura rien, pas un échec gratuit.
                    raise ImageBilledButLost(f"{plan_id} : réponse illisible (corps {type(data).__name__})")
    except aiohttp.ConnectionTimeoutError as e:
        # Délai écoulé avant même d'établir la connexion : la requête n'est jamais partie.
        log.warning("Génération %s %s échouée (connexion) : %s", provider, plan_id, e)
        return None
    except TimeoutError as e:
        # Les deux fournisseurs répondent de façon synchrone : la requête est partie, donc passé le
        # délai la génération tourne probablement encore côté serveur et sera facturée. On compte,
        # parce qu'une erreur de prudence ne coûte qu'une image de moins, quand l'inverse laisse un
        # rôle boucler aux frais du propriétaire.
        raise ImageBilledButLost(f"{plan_id} : délai dépassé, facturation probable") from e
    except aiohttp.ClientError as e:
        if data is not None:
            # La réponse 200 était déjà lue : l'échec est postérieur à la facturation.
            raise ImageBilledButLost(f"{plan_id} : connexion perdue après la réponse ({e})") from e
        log.warning("Génération %s %s échouée : %s", provider, plan_id, e)
        return None
    return data


def ai_fallback_config() -> dict:
    """Section `media_sources.ai_fallback` de data/agent_config.json."""
    return load_agent_config().get("media_sources", {}).get("ai_fallback", {}) or {}


def ai_license_label() -> str:
    return str(ai_fallback_config().get("license", "synthetic-ai-generated"))
