from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from agent.core.queue import queue

RUNWAY_MONTH_PREFIX = "cutevideo:runway_month_cost_cents:"


def _month_key(timezone: str = "Europe/Paris") -> str:
    now = datetime.now(tz=ZoneInfo(timezone))
    return now.strftime("%Y-%m")


async def get_monthly_runway_cost_usd(channel_id: str, timezone: str = "Europe/Paris") -> float:
    try:
        key = f"{RUNWAY_MONTH_PREFIX}{channel_id}:{_month_key(timezone)}"
        raw = await queue.client.get(key)
        return int(raw or 0) / 100
    except RuntimeError:
        return 0.0


async def add_monthly_runway_cost(
    channel_id: str,
    cost_usd: float,
    timezone: str = "Europe/Paris",
) -> float:
    """Adds cost in USD, stored as integer cents. Returns new total in USD."""
    try:
        key = f"{RUNWAY_MONTH_PREFIX}{channel_id}:{_month_key(timezone)}"
        cents = max(1, round(cost_usd * 100))
        new_cents = await queue.client.incrby(key, cents)
        await queue.client.expire(key, 60 * 60 * 24 * 45)  # 45-day TTL covers full month + buffer
        return int(new_cents) / 100
    except RuntimeError:
        return 0.0


async def check_runway_budget(
    channel_id: str,
    cost_usd: float,
    budget_usd: float,
    timezone: str = "Europe/Paris",
) -> bool:
    """Returns True if generating a clip costing cost_usd stays within budget_usd."""
    current = await get_monthly_runway_cost_usd(channel_id, timezone)
    return (current + cost_usd) <= budget_usd


# ── Credit error flag ──────────────────────────────────────────────────────────

RUNWAY_CREDIT_ERROR_PREFIX = "cutevideo:runway_credit_error:"


async def set_runway_credit_error(channel_id: str) -> None:
    """Persist a 24-hour flag that Runway rejected a request due to insufficient credits."""
    try:
        key = f"{RUNWAY_CREDIT_ERROR_PREFIX}{channel_id}"
        await queue.client.set(key, "1", ex=60 * 60 * 24)
    except RuntimeError:
        pass


async def get_runway_credit_error(channel_id: str) -> bool:
    try:
        key = f"{RUNWAY_CREDIT_ERROR_PREFIX}{channel_id}"
        raw = await queue.client.get(key)
        return bool(raw)
    except RuntimeError:
        return False


async def clear_runway_credit_error(channel_id: str) -> None:
    try:
        key = f"{RUNWAY_CREDIT_ERROR_PREFIX}{channel_id}"
        await queue.client.delete(key)
    except RuntimeError:
        pass
