from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Scenario
from agent.core.learning_context import LEARNING_CONTEXT_BLOCK

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un scénariste expert en vidéos documentaires YouTube éducatives.
Tu maîtrises les techniques narratives des meilleures chaînes françaises : Nota Bene,
Histoire Brève, Les Revues du Monde, Kurzgesagt (style adapté en français).
Tu produis toujours des JSON valides, sans texte avant ni après."""

USER_PROMPT_TEMPLATE = """Crée un scénario détaillé pour une vidéo de {duration_min} minutes.

CHAÎNE : {channel_name} (catégorie : {theme_category})
CONTEXTE ÉDITORIAL : {niche_prompt}
SUJET DE LA VIDÉO : "{theme}"

{content_plan_block}

{learning_block}

Retourne UNIQUEMENT un JSON valide avec cette structure :
{{
  "title": "Titre accrocheur YouTube (max 70 caractères)",
  "description": "Description YouTube SEO (max 500 caractères)",
  "segments": [
    {{
      "order": 1,
      "title": "Titre du segment",
      "duration_s": 150,
      "narration_text": "Texte complet de narration pour ce segment (minimum 300 mots)",
      "search_keywords": ["mot-clé 1 fr", "keyword 1 en", "mot-clé 2 fr", "keyword 2 en"],
      "historical_period": "Antiquité | Moyen-Âge | Moderne | Contemporain | N/A",
      "hook_type": "question | fait_surprenant | anecdote | chiffre | null"
    }}
  ],
  "total_duration_s": 1800
}}

Principes OBLIGATOIRES :
- Les 30 premières secondes = hook fort (fait surprenant ou question rhétorique)
- Rythme pédagogique : chaque segment dure 90-300 secondes
- Chaque segment a MINIMUM 4 mots-clés de recherche (2 FR + 2 EN)
- Narration naturelle et engageante, comme si tu parlais à quelqu'un
- Cliffhangers légers entre les grandes parties
- Conclusion mémorable avec invitation à s'abonner
- Total : environ {duration_min} minutes de contenu"""


def _format_content_plan_block(plan: dict[str, Any] | None) -> str:
    if not plan:
        return ""
    lines = [
        "MANDAT ÉDITORIAL (content_planner — à respecter) :",
        f"- Titre provisoire : {plan.get('provisional_title', '')}",
        f"- Angle : {plan.get('angle', '')}",
        f"- Format narratif : {plan.get('narrative_format', '')}",
        f"- Sous-thème : {plan.get('sub_theme', '')}",
        f"- Entités : {', '.join(plan.get('main_entities', []))}",
        f"- Mots-clés SEO : {', '.join(plan.get('seo_keywords', []))}",
    ]
    if plan.get("reactive_news_hook"):
        lines.append(f"- Actualité : {plan['reactive_news_hook']}")
    return "\n".join(lines)


@dataclass
class ScenarioInput:
    project_id: uuid.UUID
    theme: str
    target_duration_seconds: int
    channel_name: str
    theme_category: str
    niche_prompt: str
    learning_context_prompt: str
    content_plan_block: str = ""


@dataclass
class ScenarioOutput:
    scenario_id: uuid.UUID
    title: str
    segments: list[dict]
    total_duration_s: int


class ScenarioAgent(BaseAgent):
    """Agent 1 — Scénariste : crée la structure narrative complète."""

    name = "scenario_agent"

    async def run(self, ctx: "PipelineContext") -> Scenario:  # type: ignore[override]
        input_data = ScenarioInput(
            project_id=ctx.project_id,
            theme=ctx.theme,
            target_duration_seconds=ctx.target_duration_seconds,
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            niche_prompt=ctx.niche_prompt,
            learning_context_prompt=ctx.learning_context_prompt,
            content_plan_block=_format_content_plan_block(ctx.content_plan),
        )
        run = await self.start_run(ctx.project_id, input_data)
        try:
            scenario = await self._generate_scenario(input_data)
            await self.end_run(run, {"scenario_id": str(scenario.id), "title": scenario.segments})
            return scenario
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _generate_scenario(self, input_data: ScenarioInput) -> Scenario:
        duration_min = input_data.target_duration_seconds // 60
        prompt = USER_PROMPT_TEMPLATE.format(
            theme=input_data.theme,
            duration_min=duration_min,
            channel_name=input_data.channel_name,
            theme_category=input_data.theme_category,
            niche_prompt=input_data.niche_prompt or "Vidéo éducative française",
            content_plan_block=input_data.content_plan_block,
            learning_block=LEARNING_CONTEXT_BLOCK.format(
                learning_context_prompt=input_data.learning_context_prompt,
            ),
        )

        raw = await self._call_claude(prompt, system=SYSTEM_PROMPT, max_tokens=8192)
        data = self._parse_json(raw)

        async with AsyncSessionFactory() as session:
            scenario = Scenario(
                project_id=input_data.project_id,
                segments=data.get("segments", []),
                total_duration_s=data.get("total_duration_s", input_data.target_duration_seconds),
                iteration=1,
            )
            session.add(scenario)

            from agent.core.database import Project
            from sqlalchemy import update
            await session.execute(
                update(Project)
                .where(Project.id == input_data.project_id)
                .values(title=data.get("title"))
            )
            await session.commit()
            await session.refresh(scenario)

        logger.info(
            "Scénario créé : %d segments, %d s total",
            len(scenario.segments or []),
            scenario.total_duration_s or 0,
        )
        return scenario

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
