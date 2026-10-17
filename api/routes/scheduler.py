from __future__ import annotations

import uuid
from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from agent.core.database import User
from agent.scheduler import jobs
from agent.scheduler.config import InvalidJobConfigError
from agent.scheduler.service import scheduler_service
from api.deps import get_current_user, require_admin_user

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


class SchedulerRunResponse(BaseModel):
    id: uuid.UUID
    job_id: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    result_json: dict | None
    error: str | None

    model_config = {"from_attributes": True}


class JobConfigUpdate(BaseModel):
    enabled: bool | None = None
    cron: str | None = None
    timezone: str | None = None
    params: dict[str, Any] | None = None


class JobRunResponse(BaseModel):
    job_id: str
    status: str
    result: dict | None = None


@router.get("/status")
async def get_scheduler_status(_: User = Depends(require_admin_user)) -> dict:
    return await scheduler_service.get_status()


@router.get("/jobs")
async def list_scheduler_jobs(_: User = Depends(require_admin_user)) -> list[dict]:
    return await scheduler_service.list_jobs_with_last_run()


@router.get("/upcoming")
async def list_upcoming_jobs(_: User = Depends(get_current_user)) -> list[dict]:
    """Lecture seule : prochaines tâches planifiées, leur rôle et leur dernier statut.

    Accessible à tout utilisateur authentifié (pas seulement admin) car aucune
    action de déclenchement n'est exposée — affichage uniquement.
    """
    return await scheduler_service.list_jobs_with_last_run()


@router.get("/runs", response_model=list[SchedulerRunResponse])
async def list_scheduler_runs(
    job_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_admin_user),
) -> list[SchedulerRunResponse]:
    runs = await scheduler_service.list_runs(job_id=job_id, limit=limit)
    return [SchedulerRunResponse.model_validate(r) for r in runs]


@router.post("/jobs/{job_id}/run", response_model=JobRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_job(job_id: str, _: User = Depends(require_admin_user)) -> JobRunResponse:
    if job_id not in jobs.JOB_REGISTRY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job introuvable")
    try:
        result = scheduler_service.launch_job(job_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return JobRunResponse(job_id=job_id, status=result["status"])


@router.put("/jobs/{job_id}")
async def update_job_config(
    job_id: str, body: JobConfigUpdate, _: User = Depends(require_admin_user)
) -> dict[str, Any]:
    if job_id not in jobs.JOB_REGISTRY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job introuvable")
    try:
        config = await scheduler_service.update_job(job_id, **body.model_dump(exclude_unset=True))
    except InvalidJobConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return config.to_dict()


@router.post("/start")
async def start_scheduler(_: User = Depends(require_admin_user)) -> dict[str, Any]:
    """Active le scheduler (persisté en base) ; il ne tourne que si ce processus y est autorisé."""
    await scheduler_service.set_enabled(True)
    return {"status": "started" if scheduler_service.running else "blocked", "running": scheduler_service.running}


@router.post("/stop")
async def stop_scheduler(_: User = Depends(require_admin_user)) -> dict[str, Any]:
    await scheduler_service.set_enabled(False)
    return {"status": "stopped", "running": False}
