from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Project
from agent.core.learning_context import LEARNING_CONTEXT_BLOCK
from agent.agents.scenario_agent import (
    MOOD_FIELD_DOC,
    _format_content_plan_block,
    _format_creative_brief_block,
    _format_critic_feedback_block,
    _format_fact_check_feedback_block,
    _format_research_block,
    _format_research_rules_block,
)

logger = logging.getLogger(__name__)

OUTLINE_CONFIG_KEY = "scenario_outline"

SYSTEM_PROMPT = """Tu es un chef de projet éditorial (script-doctor) pour des vidéos YouTube.
Tu conçois l'ARCHITECTURE narrative — le « traitement » d'un studio — PAS le texte de narration.
Tu décides : découpage en segments, arc tension → révélation → payoff, allocation des faits
surprenants, accroche, durées cibles et ambiance (mood) par segment.
Tu produis toujours un JSON valide, sans texte avant ni après. Tu n'écris JAMAIS de narration."""

USER_PROMPT_LONG = """Conçois l'ARCHITECTURE (squelette) d'une vidéo de {duration_min} minutes.
N'écris PAS la narration — uniquement la structure.

CHAÎNE : {channel_name} (catégorie : {theme_category})
THÈME CHAÎNE : {theme_prompt}
CONTEXTE ÉDITORIAL : {niche_prompt}
TON ÉDITORIAL : {editorial_tone}
{creative_brief_block}SUJET DE LA VIDÉO : "{theme}"

{content_plan_block}

{research_block}

{learning_block}

Retourne UNIQUEMENT un JSON valide :
{{
  "title": "Titre accrocheur YouTube (max 70 caractères)",
  "description": "Description YouTube SEO (max 500 caractères)",
  "segments": [
    {{
      "order": 1,
      "title": "Titre du segment",
      "duration_s": 150,
      "needs_voice": true,
      "needs_music": true,
      "mood": "inspirant",
      "hook_type": "question | fait_surprenant | anecdote | chiffre | null",
      "strip_source_audio": true,
      "intent": "Rôle narratif du segment en 1-2 phrases : ce qu'il doit accomplir, quel fait surprenant du brief il exploite, quelle émotion viser. PAS de narration rédigée."
    }}
  ],
  "total_duration_s": 1800
}}

Principes OBLIGATOIRES :
- Arc narratif : tension → révélation → payoff, lisible dans les titres et `intent`
- Segment 1 : accroche / paradoxe (question rhétorique) — hook fort dans les 30 premières secondes
- Segments milieu : mécanisme, preuves, approfondissement
- Dernier segment : conclusion mémorable + clôture marquante
- Répartir les 3 faits surprenants du brief recherche (hook ou segment 2) via les `intent`
- Durées cohérentes, total ≈ {duration_min} minutes
- `mood` varié et adapté à la progression émotionnelle (hook énergique → conclusion posée)

{mood_field_doc}
CHAMP needs_voice — true par défaut pour le contenu éducatif.
CHAMP needs_music — true si un bed musical sert le segment.
CHAMP strip_source_audio — true si la source doit être muette (voix/musique seules).

{research_rules_block}
{critic_feedback_block}
{fact_check_feedback_block}
NE rédige aucun texte de narration : c'est l'étape suivante (scénariste) qui l'écrira."""

USER_PROMPT_SHORT = """Conçois l'ARCHITECTURE d'un SHORT vertical de {min_duration_s} à {max_duration_s} secondes.
N'écris PAS la narration — uniquement la structure.

CHAÎNE : {channel_name} (catégorie : {theme_category})
THÈME CHAÎNE : {theme_prompt}
CONTEXTE : {niche_prompt}
TON : {editorial_tone}
{creative_brief_block}SUJET : "{theme}"

{content_plan_block}

{research_block}

{learning_block}

Retourne UNIQUEMENT ce JSON :
{{
  "title": "Titre accrocheur (max 60 car.)",
  "description": "Description courte",
  "segments": [
    {{
      "order": 1,
      "title": "Hook",
      "duration_s": {segment_duration},
      "needs_voice": true,
      "needs_music": true,
      "mood": "energique",
      "hook_type": "fait_surprenant",
      "strip_source_audio": true,
      "intent": "Rôle du segment en 1 phrase (accroche, twist, chute). PAS de narration."
    }}
  ],
  "total_duration_s": {target_duration_s}
}}

RÈGLES SHORT :
- 1 à 3 segments ; total indicatif {min_duration_s}–{max_duration_s} s (calibré post-voix)
- Segment 1 = hook immédiat (les 3 premières secondes décident du scroll)
- `mood` varié ; progression punchy
- needs_voice true par défaut pour l'éducatif

{mood_field_doc}
{research_rules_block}
{critic_feedback_block}
{fact_check_feedback_block}
NE rédige aucun texte de narration : c'est l'étape suivante (scénariste) qui l'écrira."""


class OutlineAgent(BaseAgent):
    """Agent 1a — Architecte éditorial : produit le squelette narratif (sans narration).

    P2 — sépare le « traitement / séquencier » (structure) de l'« écriture du script ».
    Le squelette est validable/critiquable à bas coût avant d'engager l'écriture des narrations.
    """

    name = "outline_agent"

    async def run(self, ctx: "PipelineContext") -> dict[str, Any]:  # type: ignore[override]
        run = await self.start_run(ctx.project_id, {"theme": ctx.theme}, iteration=ctx.iteration)
        try:
            outline = await self._generate_outline(ctx)
            await self._persist(ctx.project_id, outline)
            await self.end_run(run, {"segments": len(outline.get("segments", []))})
            logger.info("Outline créé : %d segments", len(outline.get("segments", [])))
            return outline
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _generate_outline(self, ctx: "PipelineContext") -> dict[str, Any]:
        cfg = ctx.channel_config
        is_short = cfg.production_mode == "shorts_only" or ctx.target_duration_seconds <= 120
        theme_prompt = ctx.channel.theme_prompt or ctx.niche_prompt or ""
        learning_block = LEARNING_CONTEXT_BLOCK.format(
            learning_context_prompt=ctx.learning_context_prompt,
        )
        common = dict(
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            theme_prompt=theme_prompt or ctx.niche_prompt,
            niche_prompt=ctx.niche_prompt or "Vidéo éducative française",
            editorial_tone=cfg.editorial_tone,
            creative_brief_block=_format_creative_brief_block(cfg.creative_brief),
            theme=ctx.theme,
            content_plan_block=_format_content_plan_block(ctx.content_plan),
            research_block=_format_research_block(ctx.research_brief),
            research_rules_block=_format_research_rules_block(ctx.research_brief),
            learning_block=learning_block,
            critic_feedback_block=_format_critic_feedback_block(ctx.critic_feedback),
            fact_check_feedback_block=_format_fact_check_feedback_block(ctx.fact_check_feedback),
            mood_field_doc=MOOD_FIELD_DOC,
        )

        if is_short:
            segment_duration = min(30, max(15, ctx.target_duration_seconds // 2))
            target_duration = min(
                cfg.max_short_duration_s,
                max(cfg.min_short_duration_s, ctx.target_duration_seconds),
            )
            prompt = USER_PROMPT_SHORT.format(
                min_duration_s=cfg.min_short_duration_s,
                max_duration_s=cfg.max_short_duration_s,
                target_duration_s=target_duration,
                segment_duration=segment_duration,
                **common,
            )
        else:
            duration_min = max(1, ctx.target_duration_seconds // 60)
            prompt = USER_PROMPT_LONG.format(duration_min=duration_min, **common)

        raw = await self._call_claude(prompt, system=SYSTEM_PROMPT, max_tokens=2048)
        data = _parse_json(raw)
        return _sanitize_outline(data, ctx.target_duration_seconds)

    @staticmethod
    async def _persist(project_id: uuid.UUID, outline: dict[str, Any]) -> None:
        from sqlalchemy import update

        async with AsyncSessionFactory() as session:
            project = await session.get(Project, project_id)
            config = dict(project.config or {}) if project else {}
            config[OUTLINE_CONFIG_KEY] = outline
            await session.execute(
                update(Project).where(Project.id == project_id).values(config=config)
            )
            await session.commit()


async def load_outline(project_id: uuid.UUID) -> dict[str, Any] | None:
    """Recharge l'outline persisté (utilisé par le scénariste sur reprise/restart)."""
    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
        if not project:
            return None
        outline = (project.config or {}).get(OUTLINE_CONFIG_KEY)
        return outline if isinstance(outline, dict) and outline.get("segments") else None


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(raw)


def _sanitize_outline(data: dict[str, Any], target_duration_s: int) -> dict[str, Any]:
    """Garantit un squelette exploitable (ordres, champs structurels présents)."""
    segments = data.get("segments") or []
    cleaned: list[dict[str, Any]] = []
    for i, seg in enumerate(segments, start=1):
        if not isinstance(seg, dict):
            continue
        cleaned.append(
            {
                "order": int(seg.get("order") or i),
                "title": str(seg.get("title") or f"Segment {i}"),
                "duration_s": int(seg.get("duration_s") or 0),
                "needs_voice": bool(seg.get("needs_voice", True)),
                "needs_music": bool(seg.get("needs_music", seg.get("needs_voice", True))),
                "mood": str(seg.get("mood") or "calme"),
                "hook_type": seg.get("hook_type"),
                "strip_source_audio": bool(seg.get("strip_source_audio", True)),
                "intent": str(seg.get("intent") or "").strip(),
            }
        )
    return {
        "title": str(data.get("title") or ""),
        "description": str(data.get("description") or ""),
        "segments": cleaned,
        "total_duration_s": int(data.get("total_duration_s") or target_duration_s),
    }
