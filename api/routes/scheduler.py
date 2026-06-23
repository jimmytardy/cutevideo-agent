from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from agent.core.database import User
from agent.scheduler import jobs
from agent.scheduler.service import scheduler_service
from api.deps import require_admin_user

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


class JobRunResponse(BaseModel):
    job_id: str
    status: str
    result: dict | None = None


@router.get("/status")
async def get_scheduler_status(_: User = Depends(require_admin_user)) -> dict:
    return scheduler_service.get_status()


@router.get("/jobs")
async def list_scheduler_jobs(_: User = Depends(require_admin_user)) -> list[dict]:
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


@router.post("/start")
async def start_scheduler(_: User = Depends(require_admin_user)) -> dict[str, str]:
    await scheduler_service.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_scheduler(_: User = Depends(require_admin_user)) -> dict[str, str]:
    await scheduler_service.stop()
    return {"status": "stopped"}
