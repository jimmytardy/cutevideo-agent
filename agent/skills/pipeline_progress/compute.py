"""Progression du pipeline Claude Studio : 5 rôles par itération, d'après les AgentRun."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.claude_studio import STUDIO_AGENT_ORDER
from agent.core.database import AgentRun, Project
from agent.skills.pipeline_progress.models import AgentProgressData, PipelineProgressSnapshot

_STATUS_PROGRESS: dict[str, tuple[int, str]] = {
    "success": (100, "Terminé"),
    "running": (50, "En cours"),
    "failed": (0, "Échec"),
    "stopped": (0, "Arrêté"),
}


def _progress(run: AgentRun | None) -> AgentProgressData:
    if run is None:
        return AgentProgressData(done=0, total=1, percent=0)
    percent, detail = _STATUS_PROGRESS.get(run.status or "", (0, None))
    return AgentProgressData(done=1 if percent == 100 else 0, total=1, percent=percent, detail=detail)


async def compute_pipeline_progress(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> PipelineProgressSnapshot:
    if await session.get(Project, project_id) is None:
        raise ValueError(f"Projet introuvable : {project_id}")

    result = await session.execute(
        select(AgentRun)
        .where(AgentRun.project_id == project_id, AgentRun.agent_name.in_(STUDIO_AGENT_ORDER))
        .order_by(AgentRun.started_at.asc())
    )
    latest: dict[tuple[int, str], AgentRun] = {}
    for run in result.scalars().all():
        latest[(run.iteration or 1, run.agent_name or "")] = run

    iterations: dict[int, dict[str, AgentProgressData]] = {}
    for iteration in sorted({it for it, _ in latest} or {1}):
        iterations[iteration] = {
            name: _progress(latest.get((iteration, name))) for name in STUDIO_AGENT_ORDER
        }
    return PipelineProgressSnapshot(iterations=iterations)
