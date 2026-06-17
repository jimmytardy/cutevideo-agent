from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from agent.agents.scenario_agent import (
    AVAILABLE_SOURCES,
    SYSTEM_PROMPT_SHORT,
    _format_creative_brief_block,
    _format_research_block,
    _format_research_rules_block,
)
from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Scenario
from agent.core.json_parse import parse_json_text
from agent.core.learning_context import LEARNING_CONTEXT_BLOCK
from agent.core.short_derivation import DerivedShortPlan
from agent.core.visual_beats_prompt import SCENARIO_VOICE_BEATS_CONTEXT
from agent.skills.media.segment_beats_media import ensure_visual_beats_on_segments

logger = logging.getLogger(__name__)

SHORT_PRODUCER_SYSTEM = """Tu es un scénariste expert en shorts verticaux viraux (TikTok, YouTube Shorts, Reels).
Tu crées des mini-scénarios autonomes à partir d'une vidéo longue existante — angle différent, hook immédiat, rythme court.
Tu retournes UNIQUEMENT du JSON valide."""

DERIVATION_PROMPT = """Crée un mini-scénario SHORT vertical de {min_duration_s} à {max_duration_s} secondes, dérivé de la vidéo longue ci-dessous.

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
  "total_duration_s": {target_duration_s}
}}

RÈGLES :
- 1 à 3 segments de 15-30 s ; durée totale indicative {min_duration_s}–{max_duration_s} s (durée réelle post-voix)
- Angle DISTINCT de la vidéo longue (focus sur un fait, une anecdote, une question)
- Hook dans les 3 premières secondes de narration
- Réutiliser les faits de la recherche — n'invente rien
- Mots-clés précis liés au SUJET, pas de termes génériques seuls
- source_hint : sources gratuites uniquement (pas "ai")

{research_rules_block}
{sources_block}
{visual_beats_rules}"""

FALLBACK_ANGLES_PROMPT = """La vidéo longue « {theme} » n'a pas de shorts planifiés.
Propose {count} angles courts distincts ({min_duration_s}-{max_duration_s} s chacun) pour des shorts viraux autonomes.

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


def postprocess_derivation_segments(
    raw_segments: list[dict[str, Any]],
    *,
    min_beats: int,
    max_beats: int,
    editorial_tone: str,
    theme_category: str,
    vb_config: Any,
) -> list[dict[str, Any]]:
    """Post-traitement des segments dérivés : pas de visual_beats sur segments voix."""
    voice_segments: list[dict[str, Any]] = []
    no_voice_segments: list[dict[str, Any]] = []
    for seg in raw_segments:
        if not isinstance(seg, dict):
            continue
        seg = dict(seg)
        has_voice = (
            seg.get("needs_voice", True) is not False
            and bool((seg.get("narration_text") or "").strip())
        )
        if has_voice:
            seg.pop("visual_beats", None)
            voice_segments.append(seg)
        else:
            no_voice_segments.append(seg)

    if no_voice_segments:
        enriched = ensure_visual_beats_on_segments(
            no_voice_segments,
            is_short=True,
            min_beats=min_beats,
            max_beats=max_beats,
            editorial_tone=editorial_tone,
            theme_category=theme_category,
            vb_config=vb_config,
        )
        enriched_by_order = {int(s.get("order", 0)): s for s in enriched}
        for seg in no_voice_segments:
            voice_segments.append(enriched_by_order.get(int(seg.get("order", 0)), seg))
    return sorted(voice_segments, key=lambda s: int(s.get("order", 0)))


def clamp_short_total_duration(
    value: int | None,
    *,
    min_duration_s: int,
    max_duration_s: int,
    fallback: int,
) -> int:
    return min(max_duration_s, max(min_duration_s, int(value or fallback)))


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
        min_d = ctx.channel_config.min_short_duration_s
        max_d = ctx.channel_config.max_short_duration_s
        segment_duration = min(30, max(15, duration_s // 2))
        planned_list = list(ctx.planned_shorts or [])

        if planned_only and not planned_list:
            logger.info("planned_only sans planned_shorts — aucun short natif généré")
            return []

        if not planned_list:
            max_shorts = max(ctx.channel_config.daily_quotas.short, 1)
            planned_list = await self._generate_fallback_angles(
                ctx, long_scenario, count=min(max_shorts, 3), min_d=min_d, max_d=max_d
            )

        plans: list[DerivedShortPlan] = []
        for idx, planned in enumerate(planned_list):
            plan = await self._generate_one_plan(
                ctx,
                long_scenario=long_scenario,
                planned_short=planned,
                index=idx,
                duration_s=duration_s,
                min_duration_s=min_d,
                max_duration_s=max_d,
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
        min_d: int,
        max_d: int,
    ) -> list[dict[str, Any]]:
        prompt = FALLBACK_ANGLES_PROMPT.format(
            theme=ctx.theme,
            count=count,
            min_duration_s=min_d,
            max_duration_s=max_d,
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
        min_duration_s: int,
        max_duration_s: int,
        segment_duration: int,
    ) -> DerivedShortPlan | None:
        target_duration = min(max_duration_s, max(min_duration_s, duration_s))
        vb_ctx = dict(SCENARIO_VOICE_BEATS_CONTEXT)
        creative_brief_block = _format_creative_brief_block(ctx.channel_config.creative_brief)
        learning_block = LEARNING_CONTEXT_BLOCK.format(
            learning_context_prompt=ctx.learning_context_prompt,
        )
        prompt = DERIVATION_PROMPT.format(
            min_duration_s=min_duration_s,
            max_duration_s=max_duration_s,
            target_duration_s=target_duration,
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
            max_tokens=8192,
        )
        data = self._parse_json(raw)

        raw_segments = [dict(seg) for seg in data.get("segments", []) if isinstance(seg, dict)]
        segments = postprocess_derivation_segments(
            raw_segments,
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
            total_duration_s=clamp_short_total_duration(
                data.get("total_duration_s"),
                min_duration_s=min_duration_s,
                max_duration_s=max_duration_s,
                fallback=target_duration,
            ),
            planned_short=planned_short,
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        return parse_json_text(raw, "short_producer_agent")
