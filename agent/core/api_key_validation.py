"""État des clés API utilisateur via un appel de test minimal.

`check_api_key()` interroge le fournisseur et classe le résultat (`KeyHealth.status`) :

- `ok`          : la clé fonctionne ;
- `invalid`     : clé refusée (inconnue, révoquée, mauvaise région…) ;
- `expired`     : token expiré (YouTube, Instagram, Gemini) ;
- `no_credit`   : crédit / solde épuisé (Anthropic, fal, Post for Me, Zernio) ;
- `quota`       : quota ou limite de débit atteint, la clé redeviendra utilisable ;
- `unavailable` : test non concluant (réseau, 5xx, dépendance absente).

Appels utilisés (aucune génération utile ; seul Anthropic consomme quelques tokens, car
`GET /v1/models` ne révèle pas un crédit épuisé) :

- anthropic    : POST /v1/messages, 1 token de sortie sur le plus petit modèle (clé API seulement :
                 un token d'abonnement `sk-ant-oat…` est refusé)
- gemini       : génération d'1 token (`models.list()` accepte des tokens « AQ. » refusés ensuite)
- fal          : POST sans payload valide → 422 si la clé est bonne
- gcp          : chargement du compte de service + obtention d'un token OAuth
- azure_speech : POST issueToken (token éphémère, aucune synthèse)
- postforme    : GET /v1/social-accounts?limit=1 (lecture seule)
- zernio       : GET /v1/accounts (lecture seule)
- youtube      : échange du refresh token contre un access token (application OAuth de la plateforme)
- instagram    : GET /me sur la Graph API (lecture seule) ; `page_id` requis
- claude_subscription : `claude -p` minimal avec le token (`sk-ant-oat…`, admins seulement), via le
                 CLI non modifié ; consomme une réponse d'1 phrase sur l'abonnement

`validate_api_key()` (enregistrement d'une clé) ne bloque que sur `invalid` / `expired`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import httpx

from agent.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
# Remplacé par un httpx.MockTransport dans les tests.
_transport: httpx.AsyncBaseTransport | None = None

KeyStatus = Literal["ok", "invalid", "expired", "no_credit", "quota", "unavailable"]
BLOCKING_STATUSES: frozenset[str] = frozenset({"invalid", "expired"})


@dataclass(frozen=True)
class KeyHealth:
    status: KeyStatus
    detail: str = ""


OK = KeyHealth("ok")


class ApiKeyValidationError(ValueError):
    """La clé API a été testée et rejetée par le provider."""


async def validate_api_key(provider: str, key: str, metadata: dict | None = None) -> None:
    """Teste une clé avant enregistrement. Lève ApiKeyValidationError si elle est invalide ou expirée."""
    health = await check_api_key(provider, key, metadata)
    if health.status in BLOCKING_STATUSES:
        raise ApiKeyValidationError(health.detail)


async def check_api_key(provider: str, key: str, metadata: dict | None = None) -> KeyHealth:
    """État de la clé chez le fournisseur (jamais d'exception)."""
    key = (key or "").strip()
    if not key:
        return KeyHealth("invalid", "La clé est vide.")
    meta = metadata or {}
    checkers: dict[str, Callable[[], Awaitable[KeyHealth]]] = {
        "anthropic": lambda: _check_anthropic(key),
        "gemini": lambda: _check_gemini(key),
        "fal": lambda: _check_fal(key),
        "gcp": lambda: _check_gcp(key),
        "azure_speech": lambda: _check_azure(key, meta),
        "postforme": lambda: _check_bearer_get(
            key, "https://api.postforme.dev/v1/social-accounts?limit=1", "Post for Me"
        ),
        "zernio": lambda: _check_bearer_get(key, "https://zernio.com/api/v1/accounts", "Zernio"),
        "youtube": lambda: _check_youtube(key),
        "instagram": lambda: _check_instagram(key, meta),
        "claude_subscription": lambda: _check_claude_subscription(key),
    }
    checker = checkers.get(provider)
    if checker is None:
        return KeyHealth("unavailable", "Aucun test disponible pour ce service.")
    try:
        return await checker()
    except Exception as exc:  # noqa: BLE001 - test non concluant
        logger.warning("Test de la clé %s non concluant : %s", provider, exc)
        return KeyHealth("unavailable", f"Test non concluant ({type(exc).__name__}).")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT, transport=_transport)


def _text(resp: httpx.Response) -> str:
    return resp.text.lower()


async def _check_anthropic(key: str) -> KeyHealth:
    if key.startswith("sk-ant-oat"):
        # Anthropic interdit aux applications de stocker les identifiants d'abonnement Claude.ai.
        return KeyHealth(
            "invalid",
            "Ceci est un token d'abonnement Claude : collez une clé API (sk-ant-api…) de la console Anthropic "
            "(un admin peut l'enregistrer comme « Abonnement Claude »).",
        )
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    body = {"model": "claude-haiku-4-5-20251001", "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]}
    async with _client() as client:
        resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
    text = _text(resp)
    if resp.is_success:
        return OK
    if "credit balance" in text or resp.status_code == 402:
        return KeyHealth("no_credit", "Crédit Anthropic épuisé : rechargez-le dans la console Anthropic (Plans & Billing).")
    if resp.status_code in (401, 403):
        return KeyHealth("invalid", "Clé Anthropic invalide ou non autorisée.")
    if resp.status_code == 429:
        return KeyHealth("quota", "Limite de débit Anthropic atteinte : réessayez plus tard.")
    return KeyHealth("unavailable", f"Anthropic a répondu {resp.status_code}.")


async def _check_gemini(key: str) -> KeyHealth:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    def _call() -> None:
        # Garder une référence : un client libéré ferme sa connexion avant la requête.
        client = genai.Client(api_key=key)
        client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents="ok",
            config=types.GenerateContentConfig(max_output_tokens=1),
        )

    try:
        await asyncio.to_thread(_call)
    except genai_errors.ClientError as exc:
        return _classify_gemini(getattr(exc, "code", None), str(exc))
    return OK


def _classify_gemini(code: int | None, message: str) -> KeyHealth:
    text = message.lower()
    if code == 429 or "resource_exhausted" in text:
        return KeyHealth("quota", "Quota Gemini atteint : réessayez plus tard ou passez à l'offre payante.")
    if "expired" in text:
        return KeyHealth("expired", "Clé Gemini expirée : créez-en une nouvelle dans Google AI Studio.")
    if code in (400, 401, 403):
        return KeyHealth(
            "invalid",
            "Clé Gemini invalide : l'API Gemini Developer rejette cette clé (les tokens « AQ. » ne sont pas "
            "acceptés ici — utilisez une clé « AIza » ou configurez Vertex AI).",
        )
    return KeyHealth("unavailable", f"Gemini a répondu {code}.")


async def _check_fal(key: str) -> KeyHealth:
    # Payload vide → 422 (validation) sans rien générer si la clé est valide.
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    async with _client() as client:
        resp = await client.post("https://fal.run/fal-ai/flux/schnell", headers=headers, json={})
    text = _text(resp)
    if resp.status_code in (200, 422):
        return OK
    if "balance" in text or "locked" in text or resp.status_code == 402:
        return KeyHealth("no_credit", "Solde fal.ai épuisé : rechargez votre compte fal.ai.")
    if resp.status_code in (401, 403):
        return KeyHealth("invalid", "Clé fal.ai invalide ou non autorisée.")
    if resp.status_code == 429:
        return KeyHealth("quota", "Limite de débit fal.ai atteinte.")
    return KeyHealth("unavailable", f"fal.ai a répondu {resp.status_code}.")


async def _check_gcp(key: str) -> KeyHealth:
    try:
        info = json.loads(key)
    except json.JSONDecodeError:
        return KeyHealth("invalid", "Le JSON du compte de service GCP est invalide.")
    if not isinstance(info, dict) or info.get("type") != "service_account":
        return KeyHealth("invalid", "Fournissez la clé JSON d'un compte de service GCP (type « service_account »).")

    def _refresh() -> None:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())

    try:
        await asyncio.to_thread(_refresh)
    except Exception:  # noqa: BLE001
        return KeyHealth(
            "invalid", "Compte de service GCP invalide ou supprimé (impossible d'obtenir un token OAuth)."
        )
    return OK


async def _check_azure(key: str, metadata: dict) -> KeyHealth:
    region = str(metadata.get("region") or settings.azure_speech_region or "").strip()
    if not region:
        return KeyHealth("invalid", "Région Azure Speech requise pour valider la clé (champ « region »).")
    url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    async with _client() as client:
        resp = await client.post(url, headers={"Ocp-Apim-Subscription-Key": key, "Content-Length": "0"})
    if resp.is_success:
        return OK
    if "quota" in _text(resp) or resp.status_code == 429:
        return KeyHealth("quota", "Quota Azure Speech atteint (offre gratuite F0 ou plafond de la ressource).")
    if resp.status_code in (401, 403):
        return KeyHealth("invalid", f"Clé Azure Speech invalide ou région incorrecte (région testée : {region}).")
    return KeyHealth("unavailable", f"Azure Speech a répondu {resp.status_code}.")


async def _check_bearer_get(key: str, url: str, label: str) -> KeyHealth:
    async with _client() as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
    if resp.is_success:
        return OK
    if resp.status_code == 402:
        return KeyHealth("no_credit", f"Abonnement ou crédit {label} épuisé.")
    if resp.status_code in (401, 403):
        return KeyHealth("invalid", f"Clé {label} invalide ou non autorisée.")
    if resp.status_code == 429:
        return KeyHealth("quota", f"Limite de débit {label} atteinte.")
    return KeyHealth("unavailable", f"{label} a répondu {resp.status_code}.")


async def _check_youtube(refresh_token: str) -> KeyHealth:
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        return KeyHealth("unavailable", "Application OAuth YouTube non configurée sur la plateforme.")
    data = {
        "client_id": settings.youtube_client_id,
        "client_secret": settings.youtube_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with _client() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data=data)
    if resp.is_success:
        return OK
    if "invalid_grant" in _text(resp):
        return KeyHealth("expired", "Token Google expiré ou révoqué : reconnectez le compte YouTube.")
    if resp.status_code in (400, 401):
        return KeyHealth("invalid", "Refresh token Google invalide.")
    return KeyHealth("unavailable", f"Google OAuth a répondu {resp.status_code}.")


async def _check_instagram(token: str, metadata: dict) -> KeyHealth:
    if not str(metadata.get("page_id") or "").strip():
        return KeyHealth("invalid", "ID du compte Instagram requis (champ « page_id »).")
    async with _client() as client:
        # Forme documentée par Meta ; la valeur est masquée dans les logs httpx (agent/core/log_redaction.py).
        resp = await client.get("https://graph.facebook.com/v19.0/me", params={"access_token": token})
    if resp.is_success:
        return OK
    try:
        error = resp.json().get("error") or {}
    except ValueError:
        error = {}
    return _classify_instagram(error)


def _classify_instagram(error: dict) -> KeyHealth:
    """Codes d'erreur Graph API : 190 = token (463 / 'expired' = expiré), 2500 = token absent ou inutilisable,
    4/17/32/613 = limites de débit."""
    code, subcode = error.get("code"), error.get("error_subcode")
    message = str(error.get("message") or "").lower()
    if code in (4, 17, 32, 613):
        return KeyHealth("quota", "Limite de débit Instagram atteinte : réessayez plus tard.")
    if code == 190 and (subcode == 463 or "expired" in message):
        return KeyHealth("expired", "Token Instagram expiré : générez un nouveau token longue durée.")
    if code in (190, 2500) or subcode in (458, 460, 467):
        return KeyHealth("invalid", "Token Instagram invalide ou révoqué.")
    return KeyHealth("unavailable", f"Instagram a répondu : {error.get('message') or 'erreur inconnue'}.")


async def _check_claude_subscription(token: str) -> KeyHealth:
    from agent.core.claude_cli_llm import ClaudeCliError, claude_cli_available, probe_subscription_token

    if not token.startswith("sk-ant-oat"):
        return KeyHealth("invalid", "Collez le token affiché par `claude setup-token` (il commence par sk-ant-oat).")
    if not claude_cli_available():
        return KeyHealth("unavailable", "CLI Claude absent de ce serveur : test impossible.")
    try:
        ok, error = await probe_subscription_token(token)
    except ClaudeCliError as exc:
        return KeyHealth("unavailable", f"Test non concluant : {exc}"[:300])
    return OK if ok else _classify_claude_subscription(error)


def _classify_claude_subscription(error: str) -> KeyHealth:
    text = error.lower()
    if "limit" in text or "429" in text:
        return KeyHealth("quota", "Limite d'usage de l'abonnement Claude atteinte : réessayez après sa réinitialisation.")
    if "expired" in text:
        return KeyHealth("expired", "Token d'abonnement expiré : relancez `claude setup-token`.")
    if "401" in text or "invalid" in text or "authenticate" in text or "login" in text:
        return KeyHealth("invalid", "Token d'abonnement refusé : relancez `claude setup-token` et collez le token complet.")
    return KeyHealth("unavailable", f"Réponse inattendue du CLI : {error[:200]}")
