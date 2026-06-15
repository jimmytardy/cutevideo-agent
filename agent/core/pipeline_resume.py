from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from agent.core.database import AgentRun, AsyncSessionFactory

_CREATION_AGENT_ORDER: list[str] = [
    "research_agent",
    "scenario_agent",
    "fact_checker_agent",
    "hook_optimizer_agent",
    "diagram_specialist_agent",
    "revision_agent",
    "media_agent",
    "narrator_agent",
    "montage_planner_agent",
    "editor_agent",
    "subtitle_agent",
    "critic_agent",
]

_AGENT_ORDER_INDEX: dict[str, int] = {
    name: idx for idx, name in enumerate(_CREATION_AGENT_ORDER)
}

_FIRST_AGENT = _CREATION_AGENT_ORDER[0]


@dataclass(frozen=True)
class ResumePlan:
    step: str
    iteration: int = 1


def next_agent_after(agent_name: str) -> str:
    """Retourne l'agent suivant dans le pipeline de création."""
    idx = _AGENT_ORDER_INDEX.get(agent_name)
    if idx is None:
        return _FIRST_AGENT
    if idx + 1 >= len(_CREATION_AGENT_ORDER):
        if agent_name == "critic_agent":
            return "clipper_agent"
        return agent_name
    return _CREATION_AGENT_ORDER[idx + 1]


async def resolve_start_from(project_id: uuid.UUID) -> ResumePlan:
    """Dernier AgentRun success le plus avancé → agent suivant, sinon research_agent."""
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(AgentRun).where(
                AgentRun.project_id == project_id,
                AgentRun.status == "success",
            )
        )
        best_agent: str | None = None
        best_idx = -1
        iteration = 1
        for run in result.scalars().all():
            if not run.agent_name:
                continue
            idx = _AGENT_ORDER_INDEX.get(run.agent_name, -1)
            if idx > best_idx:
                best_idx = idx
                best_agent = run.agent_name
                iteration = run.iteration or 1

    if best_agent is None:
        return ResumePlan(step=_FIRST_AGENT, iteration=1)

    return ResumePlan(step=next_agent_after(best_agent), iteration=iteration)
