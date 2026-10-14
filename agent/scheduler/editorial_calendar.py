from __future__ import annotations

from datetime import date, timedelta

from agent.core.config import load_agent_config
from agent.scheduler.distribution_slots import paris_now

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
