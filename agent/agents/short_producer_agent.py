from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from agent.agents.scenario_agent import (
    AVAILABLE_SOURCES,
    SYSTEM_PROMPT_SHORT,
    _build_visual_beats_prompt_context,
    _format_content_plan_block,
    _format_creative_brief_block,
    _format_research_block,
    _format_research_rules_block,
)
from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Scenario
from agent.core.learning_context import LEARNING_CONTEXT_BLOCK
from agent.core.short_derivation import DerivedShortPlan
from agent.skills.media.segment_beats_media import ensure_visual_beats_on_segments

logger = logging.getLogger(__name__)

SHORT_PRODUCER_SYSTEM = """Tu es un scénariste expert en shorts verticaux viraux (TikTok, YouTube Shorts, Reels).
Tu crées des mini-scénarios autonomes à partir d'une vidéo longue existante — angle différent, hook immédiat, rythme court.
Tu retournes UNIQUEMENT du JSON valide."""

DERIVATION_PROMPT = """Crée un mini-scénario SHORT vertical de {duration_s} secondes, dérivé de la vidéo longue ci-dessous.

CHAÎNE : {channel_name} ({theme_category})
SUJET LONG : "{theme}"
{creative_brief_block}
{planned_short_block}

SEGMENTS VIDÉO LONGUE (contexte — ne pas recopier mot pour mot) :
{segments_json}

{research_block}

{learning_block}

Retourne UNIQUEMENT ce JSON :
{{
  "title": "Titre accrocheur du short (max 60 car.)",
  "hook": "Première phrase d'accroche (affichée en overlay)",
  "cta": "Invitation courte (ex: vidéo complète sur la chaîne)",
  "segments": [
    {{
      "order": 1,
      "title": "Hook",
      "duration_s": {segment_duration},
      "needs_voice": true,
      "needs_music": true,
      "narration_text": "Texte voix court et percutant",
      "on_screen_text": "",
      "search_keywords": ["kw fr", "kw en", "kw2 fr", "kw2 en"],
      "source_hint": ["pexels", "wikimedia"],
      "mood": "energique",
      "strip_source_audio": true,
      "hook_type": "fait_surprenant",
      "delivery_style": {{
        "pace": "fast",
        "emotion": "playful",
        "azure_style": "cheerful",
        "emphasis_words": []
      }}
    }}
  ],
  "total_duration_s": {duration_s}
}}

RÈGLES :
- 1 à 3 segments de 15-30 s, total ~{duration_s} s
- Angle DISTINCT de la vidéo longue (focus sur un fait, une anecdote, une question)
- Hook dans les 3 premières secondes de narration
- Réutiliser les faits de la recherche — n'invente rien
- Mots-clés précis liés au SUJET, pas de termes génériques seuls
- source_hint : sources gratuites uniquement (pas "ai")

{research_rules_block}
{sources_block}
{visual_beats_rules}"""

FALLBACK_ANGLES_PROMPT = """La vidéo longue « {theme} » n'a pas de shorts planifiés.
Propose {count} angles courts distincts (45-90 s chacun) pour des shorts viraux autonomes.

SEGMENTS LONGS :
{segments_json}

{research_block}

Retourne UNIQUEMENT :
{{
  "shorts": [
    {{
      "title": "...",
      "hook": "...",
      "cta": "...",
      "angle": "description de l'angle",
      "subject": "sujet précis du short"
    }}
  ]
}}"""


def _format_planned_short_block(planned: dict[str, Any] | None) -> str:
    if not planned:
        return "ANGLE SHORT : choisis le fait le plus viral du sujet long.\n"
    return (
        "MANDAT SHORT PLANIFIÉ (prioritaire) :\n"
        + json.dumps(planned, ensure_ascii=False, indent=2)
        + "\n"
    )


class ShortProducerAgent(BaseAgent):
    """Génère des mini-scénarios pour shorts natifs dérivés d'une vidéo longue."""

    name = "short_producer_agent"

    async def run(  # type: ignore[override]
        self,
        ctx: "PipelineContext",
        *,
        planned_only: bool = False,
    ) -> list[DerivedShortPlan]:
        run = await self.start_run(ctx.project_id, {"planned_only": planned_only})
        try:
            plans = await self._produce_plans(ctx, planned_only=planned_only)
            await self.end_run(run, {"plans_count": len(plans)})
            return plans
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _produce_plans(
        self,
        ctx: "PipelineContext",
        *,
        planned_only: bool,
    ) -> list[DerivedShortPlan]:
        async with AsyncSessionFactory() as session:
            scenario_result = await session.execute(
                select(Scenario)
                .where(Scenario.project_id == ctx.project_id)
                .order_by(Scenario.created_at.desc())
                .limit(1)
            )
            long_scenario = scenario_result.scalar_one_or_none()

        if not long_scenario:
            logger.warning("Aucun scénario long pour le projet %s", ctx.project_id)
            return []

        duration_s = ctx.channel_config.short_duration_s
        segment_duration = min(30, max(15, duration_s // 2))
        planned_list = list(ctx.planned_shorts or [])

        if planned_only and not planned_list:
            logger.info("planned_only sans planned_shorts — aucun short natif généré")
            return []

        if not planned_list:
            max_shorts = max(ctx.channel_config.daily_quotas.short, 1)
            planned_list = await self._generate_fallback_angles(
                ctx, long_scenario, count=min(max_shorts, 3)
            )

        plans: list[DerivedShortPlan] = []
        for idx, planned in enumerate(planned_list):
            plan = await self._generate_one_plan(
                ctx,
                long_scenario=long_scenario,
                planned_short=planned,
                index=idx,
                duration_s=duration_s,
                segment_duration=segment_duration,
            )
            if plan:
                plans.append(plan)

        logger.info("%d mini-scénario(s) short dérivé(s) généré(s)", len(plans))
        return plans

    async def _generate_fallback_angles(
        self,
        ctx: "PipelineContext",
        long_scenario: Scenario,
        *,
        count: int,
    ) -> list[dict[str, Any]]:
        prompt = FALLBACK_ANGLES_PROMPT.format(
            theme=ctx.theme,
            count=count,
            segments_json=json.dumps(long_scenario.segments or [], ensure_ascii=False, indent=2),
            research_block=_format_research_block(ctx.research_brief),
        )
        raw = await self._call_claude(prompt, system=SHORT_PRODUCER_SYSTEM, max_tokens=2048)
        data = self._parse_json(raw)
        return list(data.get("shorts") or [])[:count]

    async def _generate_one_plan(
        self,
        ctx: "PipelineContext",
        *,
        long_scenario: Scenario,
        planned_short: dict[str, Any],
        index: int,
        duration_s: int,
        segment_duration: int,
    ) -> DerivedShortPlan | None:
        theme_prompt = ctx.channel.theme_prompt or ctx.niche_prompt or ""
        vb_ctx = _build_visual_beats_prompt_context(
            ctx.channel_config.editorial_tone,
            ctx.theme_category,
            min_beats_short=ctx.channel_config.visual_beats.min_beats_per_short_segment,
            max_beats=ctx.channel_config.visual_beats.max_beats_per_segment,
            content_language=ctx.channel_config.content_language,
            min_diagram_duration_long=ctx.channel_config.visual_beats.min_diagram_duration_s,
            min_diagram_duration_short=ctx.channel_config.visual_beats.min_diagram_duration_short_s,
            is_short=True,
        )
        creative_brief_block = _format_creative_brief_block(ctx.channel_config.creative_brief)
        learning_block = LEARNING_CONTEXT_BLOCK.format(
            learning_context_prompt=ctx.learning_context_prompt,
        )
        prompt = DERIVATION_PROMPT.format(
            duration_s=duration_s,
            segment_duration=segment_duration,
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            theme=ctx.theme,
            creative_brief_block=creative_brief_block,
            planned_short_block=_format_planned_short_block(planned_short),
            segments_json=json.dumps(long_scenario.segments or [], ensure_ascii=False, indent=2),
            research_block=_format_research_block(ctx.research_brief),
            learning_block=learning_block,
            research_rules_block=_format_research_rules_block(ctx.research_brief),
            sources_block=AVAILABLE_SOURCES,
            **vb_ctx,
        )
        raw = await self._call_claude(
            prompt,
            system=SYSTEM_PROMPT_SHORT,
            max_tokens=4096,
        )
        data = self._parse_json(raw)

        segments = ensure_visual_beats_on_segments(
            data.get("segments", []),
            is_short=True,
            min_beats=ctx.channel_config.visual_beats.min_beats_per_short_segment,
            max_beats=ctx.channel_config.visual_beats.max_beats_per_segment,
            editorial_tone=ctx.channel_config.editorial_tone,
            theme_category=ctx.theme_category,
            vb_config=ctx.channel_config.visual_beats,
        )

        if not segments:
            logger.warning("Short dérivé %d sans segments — ignoré", index)
            return None

        return DerivedShortPlan(
            index=index,
            title=str(data.get("title") or planned_short.get("provisional_title") or ctx.theme),
            hook=str(data.get("hook") or planned_short.get("hook") or ""),
            cta=str(data.get("cta") or planned_short.get("cta") or "Vidéo complète sur la chaîne"),
            segments=segments,
            total_duration_s=int(data.get("total_duration_s") or duration_s),
            planned_short=planned_short,
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
