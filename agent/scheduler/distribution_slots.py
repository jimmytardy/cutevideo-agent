from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


@dataclass
class PlatformSlotConfig:
    weekdays: list[int]
    hours: list[int]


@dataclass
class DailyQuotas:
    long: int = 1
    short: int = 3


def parse_platform_slots(raw: dict[str, Any]) -> dict[str, PlatformSlotConfig]:
    slots: dict[str, PlatformSlotConfig] = {}
    for platform, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        weekdays = [int(d) for d in cfg.get("weekdays", [])]
        hours = [int(h) for h in cfg.get("hours", [])]
        if weekdays and hours:
            slots[str(platform)] = PlatformSlotConfig(weekdays=weekdays, hours=hours)
    return slots


def paris_now() -> datetime:
    return datetime.now(PARIS)


def paris_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=PARIS)
    end = start + timedelta(days=1)
    return start, end


def to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def is_short_video_type(video_type: str | None) -> bool:
    vtype = video_type or ""
    return vtype.startswith("short_")


def slot_datetime_utc(day: date, hour: int, tz_name: str = "Europe/Paris") -> datetime:
    tz = ZoneInfo(tz_name)
    local = datetime.combine(day, time(hour, 0), tzinfo=tz)
    return local.astimezone(timezone.utc)


def generate_candidate_slots(
    platform: str,
    platform_slots: dict[str, PlatformSlotConfig],
    tz_name: str,
    days_ahead: int = 14,
    after_utc: datetime | None = None,
    *,
    only_day: date | None = None,
) -> list[datetime]:
    """Créneaux futurs triés par date/heure (UTC)."""
    cfg = platform_slots.get(platform)
    if not cfg:
        return []

    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    after = after_utc or datetime.now(timezone.utc)
    candidates: list[datetime] = []

    if only_day is not None:
        if only_day.weekday() in cfg.weekdays:
            for hour in sorted(cfg.hours):
                slot_utc = slot_datetime_utc(only_day, hour, tz_name)
                if slot_utc > after:
                    candidates.append(slot_utc)
        return sorted(candidates)

    for offset in range(days_ahead + 1):
        day = (now_local.date() + timedelta(days=offset))
        if day.weekday() not in cfg.weekdays:
            continue
        for hour in sorted(cfg.hours):
            slot_utc = slot_datetime_utc(day, hour, tz_name)
            if slot_utc > after:
                candidates.append(slot_utc)

    return sorted(candidates)


def filter_occupied_slots(
    candidates: list[datetime],
    occupied_utc: set[datetime],
    tolerance_minutes: int = 30,
) -> list[datetime]:
    """Exclut les créneaux déjà pris (à ± tolerance)."""
    if not occupied_utc:
        return candidates
    tol = timedelta(minutes=tolerance_minutes)
    free: list[datetime] = []
    for cand in candidates:
        if any(abs(cand - occ) < tol for occ in occupied_utc):
            continue
        free.append(cand)
    return free


def pick_best_slot(candidates: list[datetime], llm_choice_index: int | None = None) -> datetime | None:
    if not candidates:
        return None
    if llm_choice_index is not None and 0 <= llm_choice_index < len(candidates):
        return candidates[llm_choice_index]
    return candidates[0]
