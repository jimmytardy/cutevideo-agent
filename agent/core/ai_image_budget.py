from __future__ import annotations

from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

from agent.core.queue import queue

AI_IMAGES_WEEK_PREFIX = "cutevideo:ai_images_week:"


def _week_key(timezone: str = "Europe/Paris") -> str:
    now = datetime.now(tz=ZoneInfo(timezone))
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


async def get_weekly_ai_image_count(channel_id: str, timezone: str = "Europe/Paris") -> int:
    try:
        key = f"{AI_IMAGES_WEEK_PREFIX}{channel_id}:{_week_key(timezone)}"
        raw = await queue.client.get(key)
        return int(raw or 0)
    except RuntimeError:
        return 0


async def increment_weekly_ai_image_count(
    channel_id: str,
    *,
    timezone: str = "Europe/Paris",
    delta: int = 1,
) -> int:
    key = f"{AI_IMAGES_WEEK_PREFIX}{channel_id}:{_week_key(timezone)}"
    try:
        new_val = await queue.client.incrby(key, delta)
        await queue.client.expire(key, 60 * 60 * 24 * 10)
        return int(new_val)
    except RuntimeError:
        return 0
