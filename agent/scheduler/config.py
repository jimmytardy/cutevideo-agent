"""Configuration du scheduler stockée en base (tables `scheduler_settings` / `scheduler_job_configs`).

Sans ligne en base : scheduler activé, chaque job garde `JOB_DEFAULTS`.
`SCHEDULER_ENABLED=false` reste un veto par processus (conteneurs qui partagent
la base sans devoir lancer de second scheduler).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger

from agent.core.database import AsyncSessionFactory, SchedulerJobConfig, SchedulerSettings

PURGE_DEFAULT_PARAMS: dict[str, int] = {"work_files_days": 7, "media_days": 30}
# Réponses aux commentaires : fenêtre après publication, délai aléatoire avant chaque réponse, plafonds.
COMMENT_REPLY_DEFAULT_PARAMS: dict[str, int] = {
    "window_hours": 2,
    "min_delay_s": 120,
    "max_delay_s": 300,
    "max_replies_per_video": 30,
    "max_replies_per_run": 20,
}
# Jobs à paramètres (entiers ≥ 0, édités sur /scheduler) ; les autres n'en ont pas.
JOB_PARAM_DEFAULTS: dict[str, dict[str, int]] = {
    "purge_old_media": PURGE_DEFAULT_PARAMS,
    "comment_reply_agent": COMMENT_REPLY_DEFAULT_PARAMS,
}


@dataclass
class JobConfig:
    job_id: str
    enabled: bool
    cron: str
    timezone: str
    params: dict[str, Any] = field(default_factory=dict)

    def trigger(self) -> CronTrigger:
        return build_trigger(self.cron, self.timezone)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


JOB_DEFAULTS: dict[str, JobConfig] = {
    "content_planner_daily": JobConfig("content_planner_daily", True, "0 6 * * *", "Europe/Paris"),
    "run_pending_projects_morning": JobConfig("run_pending_projects_morning", True, "30 6 * * *", "Europe/Paris"),
    "run_pending_projects_hourly": JobConfig("run_pending_projects_hourly", True, "0 7-23 * * *", "Europe/Paris"),
    "distribution_agent": JobConfig("distribution_agent", True, "*/15 * * * *", "UTC"),
    "purge_old_media": JobConfig("purge_old_media", True, "0 3 * * *", "UTC", dict(PURGE_DEFAULT_PARAMS)),
    "comment_reply_agent": JobConfig(
        "comment_reply_agent", True, "*/2 * * * *", "UTC", dict(COMMENT_REPLY_DEFAULT_PARAMS)
    ),
}


class InvalidJobConfigError(ValueError):
    pass


def build_trigger(cron: str, timezone: str) -> CronTrigger:
    """Crontab 5 champs (`min heure jour mois jour_semaine`) ; lève InvalidJobConfigError."""
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidJobConfigError(f"Fuseau horaire inconnu : {timezone}") from exc
    if len(cron.split()) != 5:
        raise InvalidJobConfigError("Le cron doit avoir 5 champs : minute heure jour mois jour_semaine")
    minute, hour, day, month, day_of_week = cron.split()
    try:
        return CronTrigger(minute=minute, hour=hour, day=day, month=month,
                           day_of_week=_cron_day_of_week(day_of_week), timezone=tz)
    except ValueError as exc:
        raise InvalidJobConfigError(f"Cron invalide : {exc}") from exc


_DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def _cron_day_of_week(field: str) -> str:
    """Jour de semaine crontab (0 ou 7 = dimanche) → noms APScheduler (qui numérote 0 = lundi)."""
    if field in ("*", "?"):
        return "*"
    days: set[int] = set()
    for part in field.split(","):
        span, _, step_txt = part.partition("/")
        step = int(step_txt) if step_txt.isdigit() and int(step_txt) > 0 else None
        if step_txt and step is None:
            raise ValueError(f"pas invalide : {part}")
        if span == "*":
            start, end = 0, 6
        elif "-" in span:
            first, last = span.split("-", 1)
            start, end = _cron_day_number(first), _cron_day_number(last)
        else:
            start = end = _cron_day_number(span)
        if end < start:
            raise ValueError(f"plage invalide : {part}")
        days.update(d % 7 for d in range(start, end + 1, step or 1))
    return ",".join(_DAY_NAMES[d] for d in sorted(days))


def _cron_day_number(value: str) -> int:
    if value.isdigit() and 0 <= int(value) <= 7:
        return int(value)
    if value.lower() in _DAY_NAMES:
        return _DAY_NAMES.index(value.lower())
    raise ValueError(f"jour de semaine invalide : {value}")


def _validate_params(job_id: str, params: dict[str, Any]) -> dict[str, Any]:
    defaults = JOB_PARAM_DEFAULTS.get(job_id)
    if not defaults:
        return {}
    clean: dict[str, Any] = {}
    for key, default in defaults.items():
        value = params.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise InvalidJobConfigError(f"{key} doit être un entier ≥ 0")
        clean[key] = value
    if job_id == "comment_reply_agent":
        if clean["window_hours"] < 1:
            raise InvalidJobConfigError("window_hours doit être ≥ 1")
        if clean["min_delay_s"] > clean["max_delay_s"]:
            raise InvalidJobConfigError("min_delay_s doit être ≤ max_delay_s")
    return clean


def _from_row(row: SchedulerJobConfig | None, default: JobConfig) -> JobConfig:
    if row is None:
        return JobConfig(**{**default.to_dict(), "params": dict(default.params)})
    return JobConfig(
        job_id=row.job_id,
        enabled=row.enabled,
        cron=row.cron,
        timezone=row.timezone,
        params={**default.params, **(row.params or {})},
    )


async def load_job_configs() -> dict[str, JobConfig]:
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        rows = {r.job_id: r for r in (await session.execute(select(SchedulerJobConfig))).scalars()}
    return {job_id: _from_row(rows.get(job_id), default) for job_id, default in JOB_DEFAULTS.items()}


async def load_job_config(job_id: str) -> JobConfig:
    async with AsyncSessionFactory() as session:
        row = await session.get(SchedulerJobConfig, job_id)
    return _from_row(row, JOB_DEFAULTS[job_id])


async def save_job_config(
    job_id: str,
    *,
    enabled: bool | None = None,
    cron: str | None = None,
    timezone: str | None = None,
    params: dict[str, Any] | None = None,
) -> JobConfig:
    """Valide puis enregistre (upsert) la planification d'un job."""
    if job_id not in JOB_DEFAULTS:
        raise KeyError(job_id)
    current = await load_job_config(job_id)
    updated = JobConfig(
        job_id=job_id,
        enabled=current.enabled if enabled is None else enabled,
        cron=(current.cron if cron is None else cron).strip(),
        timezone=(current.timezone if timezone is None else timezone).strip(),
        params=_validate_params(job_id, {**current.params, **(params or {})}),
    )
    build_trigger(updated.cron, updated.timezone)

    async with AsyncSessionFactory() as session:
        row = await session.get(SchedulerJobConfig, job_id)
        if row is None:
            row = SchedulerJobConfig(job_id=job_id)
            session.add(row)
        row.enabled = updated.enabled
        row.cron = updated.cron
        row.timezone = updated.timezone
        row.params = updated.params or None
        await session.commit()
    return updated


async def load_scheduler_enabled() -> bool:
    async with AsyncSessionFactory() as session:
        row = await session.get(SchedulerSettings, 1)
    return True if row is None else row.enabled


async def save_scheduler_enabled(enabled: bool) -> None:
    async with AsyncSessionFactory() as session:
        row = await session.get(SchedulerSettings, 1)
        if row is None:
            session.add(SchedulerSettings(id=1, enabled=enabled))
        else:
            row.enabled = enabled
        await session.commit()
