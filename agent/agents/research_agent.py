from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from agent.core.base_agent import BaseAgent
from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, Project
from agent.core.research_models import ResearchBrief
from agent.skills.research.gemini_grounding import load_research_config, run_gemini_research

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    """Agent 0 — Chercheur : collecte faits vérifiables via Gemini + Google Search."""

    name = "research_agent"

    async def run(self, ctx: "PipelineContext") -> ResearchBrief:  # type: ignore[override]
        cfg = load_research_config()
        run = await self.start_run(
            ctx.project_id,
            {"theme": ctx.theme, "enabled": cfg["enabled"]},
        )
        try:
            if not cfg["enabled"]:
                brief = ResearchBrief(subject_entity=ctx.theme, confidence=0.0)
                await self._persist_brief(ctx.project_id, brief)
                await self.end_run(run, {"skipped": True})
                return brief

            if not settings.google_gemini_api_key:
                raise RuntimeError("GOOGLE_GEMINI_API_KEY non configurée — recherche impossible")

            use_pro = bool(
                ctx.content_plan
                and ctx.content_plan.get("sub_theme")
                and "rare" in str(ctx.content_plan.get("angle", "")).lower()
            )
            brief = await run_gemini_research(
                theme=ctx.theme,
                theme_category=ctx.theme_category,
                niche_prompt=ctx.niche_prompt,
                content_plan=ctx.content_plan,
                api_key=settings.google_gemini_api_key,
                use_pro=use_pro,
            )
            await self._persist_brief(ctx.project_id, brief)
            await self.end_run(run, {"facts_count": len(brief.key_facts), "confidence": brief.confidence})
            return brief
        except Exception as e:
            await self.fail_run(run, e)
            raise

    @staticmethod
    async def _persist_brief(project_id: object, brief: ResearchBrief) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                raise RuntimeError(f"Projet {project_id} introuvable")
            config = dict(project.config or {})
            config["research_brief"] = brief.to_dict()
            await session.execute(
                update(Project).where(Project.id == project_id).values(config=config)
            )
            await session.commit()
