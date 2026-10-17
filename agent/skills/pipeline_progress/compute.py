"""Progression du pipeline Claude Studio : étapes de chaque itération, d'après les AgentRun."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.claude_studio import STUDIO_AGENT_ORDER
from agent.core.database import AgentRun, Project
from agent.skills.pipeline_progress.models import AgentProgressData, PipelineProgressSnapshot

_STATUS_PROGRESS: dict[str, tuple[int, str]] = {
    "success": (100, "Terminé"),
    "reused": (100, "Réutilisé"),
    "running": (50, "En cours"),
    "failed": (0, "Échec"),
    "stopped": (0, "Arrêté"),
    # Worker redémarré ou limite d'usage Claude : l'étape sera relancée à la reprise.
    "interrupted": (0, "Interrompu"),
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

    numbers = sorted({it for it, _ in latest} or {1})
    iterations: dict[int, dict[str, AgentProgressData]] = {}
    for iteration in numbers:
        iterations[iteration] = {
            name: _progress(latest.get((iteration, name)))
            for name in STUDIO_AGENT_ORDER
            if (iteration, name) in latest or _expected(name, iteration, last=numbers[-1])
        }
    return PipelineProgressSnapshot(iterations=iterations)


def _expected(agent_name: str, iteration: int, *, last: int) -> bool:
    """Étapes attendues même sans AgentRun : la boucle scénario n'a lieu qu'en itération 1,
    la miniature une seule fois, après la dernière critique."""
    if agent_name == "scenario_critic_agent":
        return iteration == 1
    if agent_name == "thumbnail_agent":
        return iteration == last
    return True
