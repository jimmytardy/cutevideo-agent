from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Scenario, Video
from agent.core.learning_context import LEARNING_CONTEXT_BLOCK

logger = logging.getLogger(__name__)

CLIPPER_SYSTEM = """Tu es un expert en création de shorts viraux pour YouTube, TikTok et Instagram.
Tu identifies les passages les plus accrocheurs et autonomes dans un scénario de vidéo éducative.
Tu retournes UNIQUEMENT du JSON valide."""

CLIPPER_PROMPT_TEMPLATE = """Analyse ce scénario de vidéo éducative et identifie les 5 à 8 meilleurs passages
pour créer des shorts viraux de 45 à 90 secondes.

CHAÎNE : {channel_name} ({theme_category})
SUJET : {theme}
DURÉE TOTALE : {duration_s} secondes

SEGMENTS :
{segments_json}

{planned_shorts_block}

{learning_block}

Pour chaque short candidat, retourne :
{{
  "clips": [
    {{
      "title": "Titre accrocheur du short",
      "hook": "Première phrase qui accroche (commence par Saviez-vous que... / Le fait que...)",
      "segment_start_order": 3,
      "segment_end_order": 4,
      "estimated_start_s": 450,
      "estimated_end_s": 540,
      "duration_s": 90,
      "shortability_score": 85,
      "reason": "Pourquoi ce passage fait un bon short",
      "cta": "Invitation à voir la vidéo complète"
    }}
  ]
}}

Critères pour un bon short :
- Autonome : compréhensible sans voir la vidéo longue
- Contient un fait surprenant ou peu connu
- Durée 45-90 secondes
- Se termine par une question ou une invitation à en savoir plus"""


def _format_planned_shorts_block(planned: list[dict[str, Any]] | None) -> str:
    if not planned:
        return ""
    return (
        "SHORTS PRIORITAIRES (content_planner — favoriser ces angles, "
        f"{len(planned)} minimum si le scénario le permet) :\n"
        + json.dumps(planned, ensure_ascii=False, indent=2)
    )


@dataclass
class ClipCandidate:
    title: str
    hook: str
    segment_start_order: int
    segment_end_order: int
    estimated_start_s: float
    estimated_end_s: float
    duration_s: float
    shortability_score: int
    reason: str
    cta: str


class ClipperAgent(BaseAgent):
    """Agent 7 — Découpeur shorts : identifie les passages forts dans la vidéo longue."""

    name = "clipper_agent"

    async def run(self, ctx: "PipelineContext") -> list[ClipCandidate]:  # type: ignore[override]
        run = await self.start_run(ctx.project_id, {"theme": ctx.theme})
        try:
            clips = await self._find_clips(ctx)
            await self.end_run(run, {"clips_count": len(clips)})
            return clips
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _find_clips(self, ctx: "PipelineContext") -> list[ClipCandidate]:
        async with AsyncSessionFactory() as session:
            scenario_result = await session.execute(
                select(Scenario).where(Scenario.project_id == ctx.project_id)
                .order_by(Scenario.created_at.desc())
            )
            scenario = scenario_result.scalar_one_or_none()

            video_result = await session.execute(
                select(Video)
                .where(Video.project_id == ctx.project_id, Video.video_type == "long")
                .order_by(Video.created_at.desc())
            )
            video = video_result.scalar_one_or_none()

        if not scenario:
            return []

        prompt = CLIPPER_PROMPT_TEMPLATE.format(
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            theme=ctx.theme,
            duration_s=video.duration_s if video else ctx.target_duration_seconds,
            segments_json=json.dumps(scenario.segments or [], ensure_ascii=False, indent=2),
            planned_shorts_block=_format_planned_shorts_block(ctx.planned_shorts),
            learning_block=LEARNING_CONTEXT_BLOCK.format(
                learning_context_prompt=ctx.learning_context_prompt,
            ),
        )

        raw = await self._call_claude(prompt, system=CLIPPER_SYSTEM, max_tokens=4096)
        data = self._parse_json(raw)

        clips = [
            ClipCandidate(**{k: v for k, v in clip.items() if k in ClipCandidate.__dataclass_fields__})
            for clip in data.get("clips", [])
        ]
        clips.sort(key=lambda c: c.shortability_score, reverse=True)

        max_clips = len(ctx.planned_shorts) if ctx.planned_shorts else 8
        clips = clips[: max(max_clips, 1)]

        logger.info("%d clips shorts identifiés", len(clips))
        return clips

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
