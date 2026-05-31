from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from agent.core.config import load_agent_config
from agent.scheduler.distribution_slots import paris_now, slot_datetime_utc

DEFAULT_PUBLICATION_LEAD_DAYS = 1


def publication_lead_days() -> int:
    cfg = load_agent_config().get("editorial_calendar", {})
    return max(1, int(cfg.get("publication_lead_days", DEFAULT_PUBLICATION_LEAD_DAYS)))


def production_day() -> date:
    """Jour calendaire de production (Paris)."""
    return paris_now().date()


def publication_target_day(*, lead_days: int | None = None) -> date:
    """Jour calendaire cible de publication (défaut : lendemain Paris)."""
    lead = lead_days if lead_days is not None else publication_lead_days()
    return production_day() + timedelta(days=lead)


def publication_target_iso(*, lead_days: int | None = None) -> str:
    return publication_target_day(lead_days=lead_days).isoformat()


def slot_on_target_day(slot_utc: datetime, target_day: date, tz_name: str = "Europe/Paris") -> bool:
    tz = ZoneInfo(tz_name)
    if slot_utc.tzinfo is None:
        slot_utc = slot_utc.replace(tzinfo=ZoneInfo("UTC"))
    local = slot_utc.astimezone(tz)
    return local.date() == target_day


def generate_slots_for_publication_day(
    platform: str,
    platform_slots: dict,
    target_day: date,
    tz_name: str = "Europe/Paris",
) -> list[datetime]:
    """Créneaux disponibles uniquement pour le jour de publication cible."""
    cfg = platform_slots.get(platform)
    if not cfg:
        return []
    if target_day.weekday() not in cfg.weekdays:
        return []
    return sorted(
        slot_datetime_utc(target_day, hour, tz_name) for hour in sorted(cfg.hours)
    )
