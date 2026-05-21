from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent.core.database import Channel
from agent.skills.publisher.composio_client import _get_composio, _parse_tool_result, _run_sync

logger = logging.getLogger(__name__)

_COMMENT_SLUGS = (
    "TIKTOK_LIST_VIDEO_COMMENTS",
    "TIKTOK_GET_VIDEO_COMMENTS",
    "TIKTOK_FETCH_VIDEO_COMMENTS",
)


@dataclass
class TikTokComment:
    platform_comment_id: str
    author_name: str
    text: str
    published_at: datetime | None


async def fetch_video_comments(
    channel: Channel,
    video_id: str,
    max_results: int = 50,
) -> list[TikTokComment]:
    if not channel.composio_tiktok_account_id:
        return []

    def _fetch() -> list[TikTokComment]:
        composio = _get_composio()
        last_error: str | None = None
        for slug in _COMMENT_SLUGS:
            try:
                result = _parse_tool_result(
                    composio.tools.execute(
                        slug=slug,
                        arguments={"video_id": video_id, "max_count": max_results},
                        user_id=channel.composio_user_id,
                        connected_account_id=channel.composio_tiktok_account_id,
                    )
                )
                if not result.get("successful", True) and result.get("error"):
                    last_error = str(result.get("error"))
                    continue
                return _parse_comments(result)
            except Exception as e:
                last_error = str(e)
                continue
        if last_error:
            logger.warning(
                "Commentaires TikTok indisponibles pour %s : %s",
                channel.slug,
                last_error,
            )
        return []

    return await _run_sync(_fetch)


def _parse_comments(result: dict[str, Any]) -> list[TikTokComment]:
    data = result.get("data") or {}
    if isinstance(data, str):
        data = json.loads(data)
    items = data.get("comments") or data.get("items") or data.get("list") or []
    if isinstance(data, list):
        items = data

    comments: list[TikTokComment] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or raw.get("comment_id") or "")
        text = str(raw.get("text") or raw.get("content") or "")
        if not cid or not text:
            continue
        comments.append(
            TikTokComment(
                platform_comment_id=cid,
                author_name=str(raw.get("author") or raw.get("username") or ""),
                text=text,
                published_at=None,
            )
        )
    return comments


async def reply_to_comment(
    channel: Channel,
    comment_id: str,
    reply_text: str,
) -> str | None:
    if not channel.composio_tiktok_account_id:
        return None

    def _reply() -> str | None:
        composio = _get_composio()
        for slug in ("TIKTOK_REPLY_TO_COMMENT", "TIKTOK_CREATE_COMMENT_REPLY"):
            try:
                result = _parse_tool_result(
                    composio.tools.execute(
                        slug=slug,
                        arguments={"comment_id": comment_id, "text": reply_text},
                        user_id=channel.composio_user_id,
                        connected_account_id=channel.composio_tiktok_account_id,
                    )
                )
                if result.get("successful", True):
                    data = result.get("data") or {}
                    if isinstance(data, dict):
                        return str(data.get("id") or data.get("reply_id") or "ok")
                    return "ok"
            except Exception:
                continue
        logger.warning("Réponse TikTok non supportée par Composio pour %s", channel.slug)
        return None

    return await _run_sync(_reply)
