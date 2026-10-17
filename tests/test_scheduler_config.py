"""Scheduler configurable en base : validation, fusion des défauts, replanification à chaud, veto env."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.scheduler import config as sched_config
from agent.scheduler import jobs
from agent.scheduler.config import JOB_DEFAULTS, InvalidJobConfigError, JobConfig, build_trigger
from agent.scheduler.service import SchedulerService


def test_job_defaults_cover_every_registered_job() -> None:
    assert set(JOB_DEFAULTS) == set(jobs.JOB_REGISTRY)
    assert {m["id"] for m in jobs.JOB_METADATA} == set(jobs.JOB_REGISTRY)
    for cfg in JOB_DEFAULTS.values():
        build_trigger(cfg.cron, cfg.timezone)


@pytest.mark.parametrize(
    "cron, tz",
    [("0 6 * *", "UTC"), ("61 * * * *", "UTC"), ("0 6 * * *", "Mars/Olympus"), ("* * * * * *", "UTC")],
)
def test_build_trigger_rejects_invalid(cron: str, tz: str) -> None:
    with pytest.raises(InvalidJobConfigError):
        build_trigger(cron, tz)


def test_purge_params_validated() -> None:
    assert sched_config._validate_params("purge_old_media", {"work_files_days": 3}) == {
        "work_files_days": 3,
        "media_days": 30,
    }
    for bad in (-1, "7", True):
        with pytest.raises(InvalidJobConfigError):
            sched_config._validate_params("purge_old_media", {"work_files_days": bad})


def test_row_merges_default_params() -> None:
    row = SimpleNamespace(job_id="purge_old_media", enabled=False, cron="0 4 * * *", timezone="UTC",
                          params={"work_files_days": 2})
    cfg = sched_config._from_row(row, JOB_DEFAULTS["purge_old_media"])  # type: ignore[arg-type]
    assert cfg.enabled is False and cfg.cron == "0 4 * * *"
    assert cfg.params == {"work_files_days": 2, "media_days": 30}
    # Sans ligne : copie des défauts (pas l'objet partagé).
    default = sched_config._from_row(None, JOB_DEFAULTS["purge_old_media"])
    default.params["work_files_days"] = 99
    assert JOB_DEFAULTS["purge_old_media"].params["work_files_days"] == 7


def _patch_config(monkeypatch, configs: dict[str, JobConfig], enabled: bool = True) -> list[bool]:
    saved: list[bool] = []

    async def load_configs():
        return configs

    async def load_enabled():
        return enabled

    async def save_enabled(value: bool):
        saved.append(value)

    async def save_job(job_id: str, **changes):
        cfg = configs[job_id]
        configs[job_id] = JobConfig(job_id, changes.get("enabled", cfg.enabled), changes.get("cron", cfg.cron),
                                    changes.get("timezone", cfg.timezone), cfg.params)
        return configs[job_id]

    monkeypatch.setattr("agent.scheduler.service.load_job_configs", load_configs)
    monkeypatch.setattr("agent.scheduler.service.load_scheduler_enabled", load_enabled)
    monkeypatch.setattr("agent.scheduler.service.save_scheduler_enabled", save_enabled)
    monkeypatch.setattr("agent.scheduler.service.save_job_config", save_job)
    return saved


def _configs(**overrides: bool) -> dict[str, JobConfig]:
    return {
        job_id: JobConfig(job_id, overrides.get(job_id, True), cfg.cron, cfg.timezone, dict(cfg.params))
        for job_id, cfg in JOB_DEFAULTS.items()
    }


@pytest.mark.asyncio
async def test_disabled_job_not_scheduled_and_hot_reschedule(monkeypatch) -> None:
    configs = _configs(distribution_agent=False)
    _patch_config(monkeypatch, configs)
    monkeypatch.setattr("agent.scheduler.service.settings.scheduler_enabled", True)
    service = SchedulerService()
    await service.start_from_config()
    try:
        assert service.running
        assert service._scheduler.get_job("distribution_agent") is None
        assert service._scheduler.get_job("purge_old_media") is not None

        await service.update_job("distribution_agent", enabled=True, cron="*/5 * * * *")
        job = service._scheduler.get_job("distribution_agent")
        assert job is not None and "*/5" in str(job.trigger)

        await service.update_job("purge_old_media", enabled=False)
        assert service._scheduler.get_job("purge_old_media") is None

        status = await service.get_status()
        purge = next(j for j in status["jobs"] if j["id"] == "purge_old_media")
        assert purge["enabled"] is False and purge["next_run_at"] is None
        assert status["process_allowed"] is True
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_env_veto_blocks_start_but_setting_is_saved(monkeypatch) -> None:
    saved = _patch_config(monkeypatch, _configs())
    monkeypatch.setattr("agent.scheduler.service.settings.scheduler_enabled", False)
    service = SchedulerService()
    await service.start_from_config()
    assert not service.running
    await service.set_enabled(True)
    assert not service.running and saved == [True]


@pytest.mark.asyncio
async def test_db_disabled_prevents_start_and_stop_persists(monkeypatch) -> None:
    saved = _patch_config(monkeypatch, _configs(), enabled=False)
    monkeypatch.setattr("agent.scheduler.service.settings.scheduler_enabled", True)
    service = SchedulerService()
    await service.start_from_config()
    assert not service.running
    await service.set_enabled(True)
    assert service.running
    await service.set_enabled(False)
    assert not service.running and saved == [True, False]


@pytest.mark.parametrize(
    "dow, expected",
    [("*", "*"), ("0", "sun"), ("7", "sun"), ("1-5", "mon,tue,wed,thu,fri"), ("0,6", "sun,sat"),
     ("*/2", "sun,tue,thu,sat"), ("sun", "sun")],
)
def test_day_of_week_follows_crontab_numbering(dow: str, expected: str) -> None:
    # APScheduler numérote 0 = lundi : la saisie crontab (0/7 = dimanche) est traduite en noms.
    assert sched_config._cron_day_of_week(dow) == expected
    build_trigger(f"0 9 * * {dow}", "Europe/Paris")
