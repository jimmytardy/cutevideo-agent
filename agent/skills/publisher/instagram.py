from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp

from agent.skills.publisher.graph_api import graph_api_url
from agent.skills.publisher.tiktok_providers import build_caption

logger = logging.getLogger(__name__)

# Un conteneur Reels est transcodé côté Meta avant d'être publiable : `media_publish` sur un conteneur encore
# IN_PROGRESS échoue (code 9007 « Media ID is not available »). On interroge `status_code` à intervalles
# croissants (quelques secondes puis une minute), 5 min au plus comme le recommande Meta.
CONTAINER_POLL_INTERVALS_S: tuple[float, ...] = (5, 10, 15, 30, 60)
CONTAINER_READY_TIMEOUT_S = 300.0
# Erreurs Graph définitives pendant l'attente : jeton (190), permission (10, 200), objet inconnu (100).
_FATAL_GRAPH_CODES = {10, 100, 190, 200}


async def upload_reel(
    video_path: Path,
    caption: str,
    hashtags: list[str],
    video_url: str,
    page_id: str,
    access_token: str,
) -> str | None:
    """Publie un Reel Instagram via Graph API avec le token du propriétaire. Retourne l'ID du media."""
    if not access_token or not page_id:
        raise RuntimeError("Credentials Instagram non configurés")

    full_caption = build_caption(caption, hashtags)  # même normalisation et même plafond (2200) que TikTok
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        container_id = await _create_container(session, video_url, full_caption, page_id, access_token)
        if not container_id:
            return None
        await wait_until_container_ready(session, container_id, access_token)
        published_id = await _publish_container(session, container_id, page_id, access_token)
    logger.info("Instagram Reel publié : %s", published_id)
    return published_id


async def _create_container(
    session: aiohttp.ClientSession, video_url: str, caption: str, page_id: str, access_token: str
) -> str | None:
    params = {"media_type": "REELS", "video_url": video_url, "caption": caption, "access_token": access_token}
    return await _graph_post(session, graph_api_url(f"{page_id}/media"), params, step="création du conteneur")


async def _publish_container(
    session: aiohttp.ClientSession, container_id: str, page_id: str, access_token: str
) -> str | None:
    params = {"creation_id": container_id, "access_token": access_token}
    return await _graph_post(session, graph_api_url(f"{page_id}/media_publish"), params, step="publication")


async def wait_until_container_ready(
    session: aiohttp.ClientSession,
    container_id: str,
    access_token: str,
    *,
    timeout_s: float = CONTAINER_READY_TIMEOUT_S,
    intervals_s: tuple[float, ...] = CONTAINER_POLL_INTERVALS_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Attend que Meta ait fini de traiter le conteneur (`status_code` FINISHED).

    Une erreur transitoire (réseau, 5xx, limite de débit) ne casse pas l'attente : on réessaie jusqu'à
    l'échéance. Lève RuntimeError avec une raison lisible dans le dashboard : `instagram_container_error`
    / `_expired` / `_timeout`, ou `instagram_graph_error` pour une erreur définitive (jeton, objet inconnu).
    """
    deadline = time.monotonic() + timeout_s
    last_state = "inconnu"
    for attempt in range(10_000):
        try:
            data = await _graph_get(
                session, graph_api_url(container_id), {"fields": "status_code,status", "access_token": access_token}
            )
        except _TransientGraphError as exc:
            last_state = f"erreur transitoire ({exc})"
        else:
            code = str(data.get("status_code") or "").upper()
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise RuntimeError(
                    f"instagram_container_{code.lower()} : {data.get('status') or 'conteneur refusé par Meta'}"
                )
            last_state = code or "inconnu"
        if time.monotonic() >= deadline:
            raise RuntimeError(f"instagram_container_timeout : traitement toujours {last_state} après {timeout_s:.0f} s")
        await sleep(intervals_s[min(attempt, len(intervals_s) - 1)])


class _TransientGraphError(RuntimeError):
    """Réseau, 5xx ou limite de débit : on peut réessayer."""


async def _graph_request(
    session: aiohttp.ClientSession, method: str, url: str, **kwargs: Any
) -> tuple[int, dict[str, Any] | None, dict[str, Any]]:
    """Requête Graph API → (statut HTTP, corps JSON ou None si illisible, objet `error` Meta ou {})."""
    async with session.request(method, url, **kwargs) as resp:
        raw = await resp.text()
        status = resp.status
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = None  # page HTML d'un 5xx, proxy…
    data = parsed if isinstance(parsed, dict) else None
    error = (data or {}).get("error") or {}
    if data is None:
        error = {"message": f"réponse non JSON (HTTP {status}) : {raw[:160]!r}"}
    return status, data, error


def _error_text(status: int, error: dict[str, Any]) -> str:
    subcode = f"/{error['error_subcode']}" if error.get("error_subcode") else ""
    return f"HTTP {status}, code {error.get('code')}{subcode} : {error.get('message')}"


async def _graph_post(
    session: aiohttp.ClientSession, url: str, params: dict[str, str], *, step: str
) -> str | None:
    """POST Graph API ; renvoie l'`id` du résultat, sinon None en journalisant ce que Meta a répondu."""
    status, data, error = await _graph_request(session, "POST", url, data=params)
    if data and data.get("id") and not error:
        return str(data["id"])
    logger.warning("Instagram : %s refusée (%s)", step, _error_text(status, error) if error else f"HTTP {status}, sans id : {data}")
    return None


async def _graph_get(session: aiohttp.ClientSession, url: str, params: dict[str, str]) -> dict[str, Any]:
    """GET Graph API ; `_TransientGraphError` si ça vaut la peine de réessayer, RuntimeError sinon."""
    try:
        status, data, error = await _graph_request(session, "GET", url, params=params)
    except (TimeoutError, aiohttp.ClientError) as exc:
        raise _TransientGraphError(f"{type(exc).__name__}: {str(exc)[:120]}") from exc
    if data is not None and not error:
        return data
    text = _error_text(status, error)
    if error.get("code") in _FATAL_GRAPH_CODES:
        raise RuntimeError(f"instagram_graph_error : {text}")
    raise _TransientGraphError(text)  # 5xx, limite de débit (4/17/32), corps illisible
