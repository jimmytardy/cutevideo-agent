from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from agent.core.database import AgentRun, Scenario

_AGENTS_CREATING_SCENARIO = frozenset({"hook_optimizer_agent", "revision_agent"})


def scenario_id_from_agent_run(run: AgentRun | None) -> uuid.UUID | None:
    """Résout l'identifiant du scénario produit ou mis à jour par un AgentRun."""
    if run is None:
        return None

    output = run.output_json or {}
    for key in ("new_scenario_id", "scenario_id"):
        raw = output.get(key)
        if raw:
            try:
                return uuid.UUID(str(raw))
            except ValueError:
                continue

    input_json = run.input_json or {}
    raw = input_json.get("scenario_id")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            return None
    return None


def _input_scenario_id(run: AgentRun) -> uuid.UUID | None:
    raw = (run.input_json or {}).get("scenario_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def _output_has_explicit_scenario_id(run: AgentRun) -> bool:
    output = run.output_json or {}
    return bool(output.get("new_scenario_id") or output.get("scenario_id"))


async def resolve_scenario_id_for_agent_run(
    run: AgentRun | None,
    project_id: uuid.UUID,
    session: AsyncSession,
) -> uuid.UUID | None:
    """Résout le scénario produit par un AgentRun, avec fallback temporel pour les anciens runs."""
    if run is None:
        return None

    direct = scenario_id_from_agent_run(run)
    agent_name = run.agent_name or ""

    if agent_name not in _AGENTS_CREATING_SCENARIO:
        return direct

    if _output_has_explicit_scenario_id(run):
        return direct

    if run.started_at is None:
        return direct

    from agent.core.database import Scenario

    input_id = _input_scenario_id(run)
    query = (
        select(Scenario.id)
        .where(
            Scenario.project_id == project_id,
            Scenario.created_at >= run.started_at,
        )
    )
    if run.ended_at is not None:
        query = query.where(Scenario.created_at <= run.ended_at)
    if input_id is not None:
        query = query.where(Scenario.id != input_id)

    query = query.order_by(Scenario.created_at.desc()).limit(1)
    result = await session.execute(query)
    created_id = result.scalar_one_or_none()
    if created_id is not None:
        return created_id

    return direct
