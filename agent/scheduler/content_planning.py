from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from agent.core.channel_config import ChannelRuntimeConfig, resolve_channel_config
from agent.core.database import AsyncSessionFactory, Channel, Project
from agent.scheduler.distribution_slots import paris_day_bounds, paris_now, to_utc


def build_editorial_identity(channel: Channel) -> dict[str, str]:
    kit: dict[str, Any] = channel.brand_kit or {}
    editorial: dict[str, Any] = (channel.config or {}).get("editorial", {})
    return {
        "theme_category": channel.theme_category,
        "channel_name": channel.name,
        "theme_prompt": channel.theme_prompt or "",
        "niche_prompt": channel.niche_prompt or "",
        "content_angle": str(kit.get("content_angle", "")),
        "target_audience": str(editorial.get("target_audience", "Grand public curieux, français")),
        "tone": str(editorial.get("tone", "Pédagogique, accessible, engageant")),
        "differentiator": str(
            editorial.get("differentiator", kit.get("content_angle", "Angle documentaire distinctif"))
        ),
    }


async def load_topic_history(
    channel_id: uuid.UUID,
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Sujets déjà traités (thème, titre, sous-thème, date)."""
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Project)
            .where(
                Project.channel_id == channel_id,
                Project.status.in_(
                    ("pending", "running", "approved", "failed")
                ),
            )
            .order_by(Project.created_at.desc())
            .limit(limit)
        )
        projects = list(result.scalars().all())

    history: list[dict[str, Any]] = []
    for p in projects:
        plan = (p.config or {}).get("content_plan", {})
        history.append(
            {
                "theme": p.theme,
                "title": p.title,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "sub_theme": plan.get("sub_theme"),
                "provisional_title": plan.get("provisional_title"),
                "main_entities": plan.get("main_entities", []),
            }
        )
    return history


async def count_planner_projects_for_publish_date(
    channel_id: uuid.UUID,
    publish_date: date,
) -> int:
    """Projets planner déjà mandatés pour une date de publication cible."""
    target = publish_date.isoformat()
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Project).where(Project.channel_id == channel_id)
        )
        projects = list(result.scalars().all())

    return sum(
        1
        for p in projects
        if (p.config or {}).get("source") == "content_planner_agent"
        and (p.config or {}).get("target_publish_date") == target
        and p.status in ("pending", "running", "approved")
    )


async def count_planner_projects_today(channel_id: uuid.UUID, day: date | None = None) -> int:
    """Rétrocompat — compte par date de publication cible (= demain par défaut)."""
    from agent.scheduler.editorial_calendar import publication_target_day

    if day is not None:
        return await count_planner_projects_for_publish_date(channel_id, day)
    return await count_planner_projects_for_publish_date(
        channel_id, publication_target_day()
    )


def production_quotas(cfg: ChannelRuntimeConfig) -> tuple[int, int]:
    return cfg.daily_quotas.long, cfg.daily_quotas.short
