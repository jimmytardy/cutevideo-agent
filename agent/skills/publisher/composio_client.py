from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from agent.core.config import settings
from agent.core.database import Channel

logger = logging.getLogger(__name__)

POLL_INTERVALS_S = (5, 10, 20, 30, 60)


def _get_composio() -> Any:
    if not settings.composio_api_key:
        raise RuntimeError("COMPOSIO_API_KEY non configuré dans .env")
    from composio import Composio

    return Composio(api_key=settings.composio_api_key)


def _run_sync(fn: Any) -> Any:
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, fn)


def tiktok_is_connected(channel: Channel) -> bool:
    return bool(channel.tiktok_enabled and channel.composio_tiktok_account_id)


def _connection_request_payload(connection_request: Any) -> dict[str, str]:
    redirect_url = getattr(connection_request, "redirect_url", None)
    connection_id = getattr(connection_request, "id", None)
    if not redirect_url or not connection_id:
        raise RuntimeError("Réponse Composio OAuth TikTok incomplète")
    return {"redirect_url": str(redirect_url), "connection_id": str(connection_id)}


async def initiate_tiktok_oauth(channel: Channel) -> dict[str, str]:
    """Démarre le flux OAuth Composio pour lier un compte TikTok à la chaîne."""

    def _initiate() -> dict[str, str]:
        composio = _get_composio()

        # SDK Composio >= 1.0 : toolkit slug + auth_config_id (plus de param toolkit= sur initiate).
        if hasattr(composio, "toolkits") and hasattr(composio.toolkits, "authorize"):
            connection_request = composio.toolkits.authorize(
                user_id=channel.composio_user_id,
                toolkit="tiktok",
            )
            return _connection_request_payload(connection_request)

        auth_config_id = settings.composio_tiktok_auth_config_id or None
        if auth_config_id and hasattr(composio.connected_accounts, "link"):
            connection_request = composio.connected_accounts.link(
                user_id=channel.composio_user_id,
                auth_config_id=auth_config_id,
                allow_multiple=True,
            )
            return _connection_request_payload(connection_request)

        if auth_config_id and hasattr(composio.connected_accounts, "initiate"):
            connection_request = composio.connected_accounts.initiate(
                user_id=channel.composio_user_id,
                auth_config_id=auth_config_id,
                allow_multiple=True,
            )
            return _connection_request_payload(connection_request)

        session = composio.create(user_id=channel.composio_user_id, toolkits=["tiktok"])
        auth = session.authorize("tiktok")
        return _connection_request_payload(auth)

    return await _run_sync(_initiate)


async def wait_for_tiktok_connection(connection_id: str, channel: Channel) -> str:
    """Attend la fin du OAuth et retourne le connected_account_id."""

    def _wait() -> str:
        composio = _get_composio()
        if hasattr(composio.connected_accounts, "wait_for_connection"):
            connected_account = composio.connected_accounts.wait_for_connection(connection_id)
            account_id = getattr(connected_account, "id", None)
            if account_id:
                return str(account_id)

        accounts = composio.connected_accounts.list(
            user_ids=[channel.composio_user_id],
            toolkit_slugs=["tiktok"],
            statuses=["ACTIVE"],
        )
        items = accounts.items if hasattr(accounts, "items") else accounts
        if items:
            return str(items[0].id)
        raise RuntimeError("Aucun compte TikTok connecté après OAuth")

    return await _run_sync(_wait)


def _parse_tool_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return {"data": result, "successful": True}


async def publish_tiktok_video(
    channel: Channel,
    video_url: str,
    caption: str,
    privacy_level: str = "PUBLIC_TO_EVERYONE",
) -> str:
    """Publie une vidéo TikTok via Composio et retourne le publish_id."""
    if not channel.composio_tiktok_account_id:
        raise RuntimeError(f"TikTok non connecté pour la chaîne {channel.slug}")

    def _publish() -> dict[str, Any]:
        composio = _get_composio()
        kwargs: dict[str, Any] = {
            "slug": "TIKTOK_PUBLISH_VIDEO",
            "arguments": {
                "video_url": video_url,
                "caption": caption,
                "privacy_level": privacy_level,
            },
        }
        if hasattr(composio, "tools") and hasattr(composio.tools, "execute"):
            kwargs["user_id"] = channel.composio_user_id
            kwargs["connected_account_id"] = channel.composio_tiktok_account_id
            return _parse_tool_result(composio.tools.execute(**kwargs))

        raise RuntimeError("SDK Composio incompatible — mettre à jour le package composio")

    result = await _run_sync(_publish)
    if not result.get("successful", True) and result.get("error"):
        raise RuntimeError(f"Échec publication TikTok : {result.get('error')}")

    data = result.get("data") or {}
    if isinstance(data, str):
        data = json.loads(data)
    publish_id = data.get("publish_id") or data.get("id") or str(data)
    await _poll_publish_status(channel, str(publish_id))
    return str(publish_id)


async def _poll_publish_status(channel: Channel, publish_id: str) -> None:
    for interval in POLL_INTERVALS_S:
        await asyncio.sleep(interval)

        def _fetch() -> dict[str, Any]:
            composio = _get_composio()
            return _parse_tool_result(
                composio.tools.execute(
                    slug="TIKTOK_FETCH_PUBLISH_STATUS",
                    arguments={"publish_id": publish_id},
                    user_id=channel.composio_user_id,
                    connected_account_id=channel.composio_tiktok_account_id,
                )
            )

        result = await _run_sync(_fetch)
        if not result.get("successful", True) and result.get("error"):
            logger.warning("Poll TikTok status : %s", result.get("error"))
            continue

        data = result.get("data") or {}
        if isinstance(data, str):
            data = json.loads(data)

        status = str(data.get("status", "")).upper()
        if status in ("PUBLISH_COMPLETE", "SUCCESS", "COMPLETED"):
            logger.info("TikTok publish %s terminé pour %s", publish_id, channel.slug)
            return
        if status in ("FAILED", "ERROR"):
            raise RuntimeError(f"Publication TikTok échouée : {data}")

    logger.warning("Timeout poll TikTok pour publish_id=%s", publish_id)


