from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from agent.core.database import AgentRun, AsyncSessionFactory, Project
from agent.core.llm_usage import LlmUsageRecord

StopReason = Literal["approved", "max_iterations", "cost_cap", "unknown"]


class AgentCostRow(BaseModel):
    agent_name: str
    usd: float
    input_tokens: int
    output_tokens: int


class IterationCostRow(BaseModel):
    iteration: int
    usd: float
    duration_s: float


class ProjectCostBreakdown(BaseModel):
    project_id: str
    total_usd: float
    cap_usd: float
    iterations_used: int
    max_iterations: int | None
    stop_reason: StopReason = "unknown"
    by_agent: list[AgentCostRow] = Field(default_factory=list)
    by_iteration: list[IterationCostRow] = Field(default_factory=list)
    elapsed_s: float = 0.0


async def persist_standalone_agent_run(
    project_id: uuid.UUID,
    agent_name: str,
    iteration: int,
    usage: LlmUsageRecord,
    *,
    status: str = "success",
    output_json: dict | None = None,
) -> None:
    """Enregistre un run agent hors BaseAgent (ex. video_analyst)."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionFactory() as session:
        run = AgentRun(
            project_id=project_id,
            agent_name=agent_name,
            status=status,
            iteration=iteration,
            output_json=output_json,
            started_at=now,
            ended_at=now,
            cost_estimate_usd=usage.cost_usd,
            llm_input_tokens=usage.input_tokens,
            llm_output_tokens=usage.output_tokens,
            llm_model=usage.model,
        )
        session.add(run)
        await session.commit()


async def sum_project_llm_cost_usd(project_id: uuid.UUID) -> float:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(func.coalesce(func.sum(AgentRun.cost_estimate_usd), 0.0)).where(
                AgentRun.project_id == project_id
            )
        )
        total = result.scalar_one()
        return float(total or 0.0)


async def project_cost_exceeded(project_id: uuid.UUID, cap_usd: float) -> bool:
    if cap_usd <= 0:
        return False
    total = await sum_project_llm_cost_usd(project_id)
    return total >= cap_usd


async def project_cost_breakdown(
    project_id: uuid.UUID,
    *,
    cap_usd: float = 0.0,
    max_iterations: int | None = None,
) -> ProjectCostBreakdown:
    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
        stop_reason: StopReason = "unknown"
        if project and isinstance(project.config, dict):
            summary = project.config.get("cost_summary") or {}
            if isinstance(summary, dict):
                raw_reason = summary.get("stop_reason")
                if raw_reason in ("approved", "max_iterations", "cost_cap"):
                    stop_reason = raw_reason  # type: ignore[assignment]

        result = await session.execute(
            select(AgentRun)
            .where(AgentRun.project_id == project_id)
            .order_by(AgentRun.started_at.asc())
        )
        runs = list(result.scalars().all())

    by_agent_map: dict[str, AgentCostRow] = {}
    by_iter_map: dict[int, IterationCostRow] = {}
    total_usd = 0.0
    first_start: datetime | None = None
    last_end: datetime | None = None
    max_iter_seen = 0

    for run in runs:
        cost = float(run.cost_estimate_usd or 0.0)
        total_usd += cost
        agent = run.agent_name or "unknown"
        if agent not in by_agent_map:
            by_agent_map[agent] = AgentCostRow(
                agent_name=agent, usd=0.0, input_tokens=0, output_tokens=0
            )
        row = by_agent_map[agent]
        row.usd = round(row.usd + cost, 6)
        row.input_tokens += int(run.llm_input_tokens or 0)
        row.output_tokens += int(run.llm_output_tokens or 0)

        iteration = int(run.iteration or 1)
        max_iter_seen = max(max_iter_seen, iteration)
        if iteration not in by_iter_map:
            by_iter_map[iteration] = IterationCostRow(iteration=iteration, usd=0.0, duration_s=0.0)
        iter_row = by_iter_map[iteration]
        iter_row.usd = round(iter_row.usd + cost, 6)
        if run.started_at and run.ended_at:
            iter_row.duration_s += (run.ended_at - run.started_at).total_seconds()

        if run.started_at and (first_start is None or run.started_at < first_start):
            first_start = run.started_at
        if run.ended_at and (last_end is None or run.ended_at > last_end):
            last_end = run.ended_at

    elapsed_s = 0.0
    if first_start and last_end:
        elapsed_s = (last_end - first_start).total_seconds()

    return ProjectCostBreakdown(
        project_id=str(project_id),
        total_usd=round(total_usd, 6),
        cap_usd=cap_usd,
        iterations_used=max_iter_seen,
        max_iterations=max_iterations,
        stop_reason=stop_reason,
        by_agent=sorted(by_agent_map.values(), key=lambda r: r.usd, reverse=True),
        by_iteration=sorted(by_iter_map.values(), key=lambda r: r.iteration),
        elapsed_s=round(elapsed_s, 1),
    )


async def persist_cost_summary(
    project_id: uuid.UUID,
    *,
    stop_reason: StopReason,
    total_usd: float,
    iterations_used: int,
) -> None:
    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return
        config = dict(project.config or {})
        config["cost_summary"] = {
            "stop_reason": stop_reason,
            "total_usd": round(total_usd, 6),
            "iterations_used": iterations_used,
        }
        project.config = config
        await session.commit()
