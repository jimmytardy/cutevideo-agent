"""Validation des clés API utilisateur via un appel de test minimal.

Chaque provider est vérifié par un appel léger qui **ne génère rien** (pas
d'image, pas de vidéo, pas de tokens facturés quand c'est possible) :

- anthropic    : GET /v1/models
- gemini       : GET /v1/models (API Gemini Developer ; rejette donc les tokens AQ.)
- fal          : POST sans payload valide -> 422 si la clé est bonne, 401 sinon
- gcp          : chargement du compte de service + obtention d'un token OAuth
- azure_speech : POST issueToken (token éphémère, aucune synthèse)
- runway       : GET /v1/organization (infos compte, aucune génération)

Principe : on ne bloque l'enregistrement **que** sur une erreur d'authentification
claire (clé invalide / refusée). Les erreurs ambiguës (réseau, 5xx, dépendance
absente) sont journalisées mais laissent passer l'enregistrement.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from agent.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_RUNWAY_API_VERSION = "2024-11-06"


class ApiKeyValidationError(ValueError):
    """La clé API a été testée et rejetée par le provider."""


async def validate_api_key(
    provider: str, key: str, metadata: dict | None = None
) -> None:
    """Teste une clé API. Lève ApiKeyValidationError si elle est clairement invalide."""
    key = (key or "").strip()
    if not key:
        raise ApiKeyValidationError("La clé est vide.")

    validators = {
        "anthropic": lambda: _validate_anthropic(key),
        "gemini": lambda: _validate_gemini(key),
        "fal": lambda: _validate_fal(key),
        "gcp": lambda: _validate_gcp(key),
        "azure_speech": lambda: _validate_azure(key, metadata or {}),
        "runway": lambda: _validate_runway(key),
    }
    validator = validators.get(provider)
    if validator is None:
        return  # provider sans test défini : on n'empêche pas l'enregistrement

    try:
        await validator()
    except ApiKeyValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - test non concluant, on ne bloque pas
        logger.warning(
            "Validation de la clé %s non concluante (enregistrement autorisé) : %s",
            provider,
            exc,
        )


async def _validate_anthropic(key: str) -> None:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=key)
    try:
        await client.models.list(limit=1)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise ApiKeyValidationError("Clé Anthropic invalide ou non autorisée.") from exc


async def _validate_gemini(key: str) -> None:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    # `models.list()` accepte certains tokens « AQ. » que `generateContent`
    # refuse — on teste donc le vrai chemin avec une génération d'1 token.
    def _check() -> None:
        client = genai.Client(api_key=key)
        client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents="ok",
            config=types.GenerateContentConfig(max_output_tokens=1),
        )

    try:
        await asyncio.to_thread(_check)
    except genai_errors.ClientError as exc:
        code = getattr(exc, "code", None)
        if code in (400, 401, 403):
            raise ApiKeyValidationError(
                "Clé Gemini invalide : l'API Gemini Developer rejette cette clé "
                "(les tokens « AQ. » ne sont pas acceptés ici — utilisez une clé "
                "« AIza » ou configurez Vertex AI)."
            ) from exc
        raise


async def _validate_fal(key: str) -> None:
    # Payload vide -> le modèle renvoie 422 (validation) sans rien générer si la
    # clé est valide ; 401/403 si la clé est mauvaise.
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://fal.run/fal-ai/flux/schnell", headers=headers, json={}
        )
    if resp.status_code in (401, 403):
        raise ApiKeyValidationError("Clé fal.ai invalide ou non autorisée.")


async def _validate_gcp(key: str) -> None:
    try:
        info = json.loads(key)
    except json.JSONDecodeError as exc:
        raise ApiKeyValidationError(
            "Le JSON du compte de service GCP est invalide."
        ) from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise ApiKeyValidationError(
            "Fournissez la clé JSON d'un compte de service GCP (type « service_account »)."
        )

    def _check() -> None:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())

    try:
        await asyncio.to_thread(_check)
    except Exception as exc:  # noqa: BLE001
        raise ApiKeyValidationError(
            "Compte de service GCP invalide (impossible d'obtenir un token OAuth)."
        ) from exc


async def _validate_azure(key: str, metadata: dict) -> None:
    region = str(metadata.get("region") or settings.azure_speech_region or "").strip()
    if not region:
        raise ApiKeyValidationError(
            "Région Azure Speech requise pour valider la clé (champ « region »)."
        )
    url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    headers = {"Ocp-Apim-Subscription-Key": key, "Content-Length": "0"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=headers)
    if resp.status_code in (401, 403):
        raise ApiKeyValidationError(
            "Clé Azure Speech invalide ou région incorrecte."
        )


async def _validate_runway(key: str) -> None:
    headers = {
        "Authorization": f"Bearer {key}",
        "X-Runway-Version": _RUNWAY_API_VERSION,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.dev.runwayml.com/v1/organization", headers=headers
        )
    if resp.status_code in (401, 403):
        raise ApiKeyValidationError("Clé Runway invalide ou non autorisée.")
