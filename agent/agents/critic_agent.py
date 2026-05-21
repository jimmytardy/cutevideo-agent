from __future__ import annotations

import json
import logging
from pathlib import Path

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, CriticReport, Scenario, Video
from agent.core.learning_context import LEARNING_CONTEXT_BLOCK

logger = logging.getLogger(__name__)

CRITIC_SYSTEM = """Tu es un expert en vidéos éducatives YouTube (style Nota Bene, Histoire Brève,
Kurzgesagt, Les Revues du Monde). Tu évalues objectivement les vidéos produites par une IA
et donnes des retours précis pour améliorer la qualité. Tu retournes UNIQUEMENT du JSON valide."""

CRITIC_PROMPT_TEMPLATE = """Analyse cette vidéo éducative et évalue-la sur 100.

CHAÎNE : {channel_name} ({theme_category})
SUJET : {theme}
DURÉE : {duration_s} secondes
ITÉRATION : {iteration}

CONTENU DU SCÉNARIO (résumé) :
{scenario_summary}

{learning_block}

CRITÈRES D'ÉVALUATION :

RYTHME (25 pts)
- Durée minimale par image respectée (jamais < {min_duration}s) ?
- Transitions fluides ?
- Cohérence tempo narration / images ?

VALEUR ÉDUCATIVE (30 pts)
- La narration apprend réellement quelque chose ?
- Les informations sont précises et sourcées ?
- Fil conducteur clair ?

QUALITÉ VISUELLE (25 pts)
- Images pertinentes par rapport à la narration ?
- Variété des sources visuelles ?
- Attributions présentes en fin de vidéo ?

ACCROCHE ET STRUCTURE (20 pts)
- Hook fort les 30 premières secondes ?
- Chapitrage clair ?
- Conclusion mémorable ?

Retourne UNIQUEMENT ce JSON :
{{
  "global_score": 75,
  "feedback": {{
    "rhythm": 20,
    "educational_value": 25,
    "visual_quality": 18,
    "structure": 12,
    "comments": "Commentaires détaillés ici"
  }},
  "decision": "approve",
  "requested_changes": []
}}

Si global_score < {min_score} : decision = "iterate" et requested_changes liste les agents à corriger :
[{{"agent": "editor_agent", "change_description": "Ralentir le segment X"}}]

Si global_score >= {min_score} : decision = "approve" et requested_changes = []"""


class CriticAgent(BaseAgent):
    """Agent 6 — Critique IA : analyse la vidéo et décide approve / iterate."""

    name = "critic_agent"

    async def run(  # type: ignore[override]
        self,
        ctx: "PipelineContext",
        video: Video,
        scenario: Scenario,
        iteration: int,
    ) -> CriticReport:
        run = await self.start_run(
            ctx.project_id,
            {"video_id": str(video.id), "iteration": iteration},
        )
        try:
            report = await self._evaluate(ctx, video, scenario, iteration)
            await self.end_run(run, {"decision": report.decision, "score": report.global_score})
            return report
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _evaluate(
        self,
        ctx: "PipelineContext",
        video: Video,
        scenario: Scenario,
        iteration: int,
    ) -> CriticReport:
        scenario_summary = self._build_scenario_summary(scenario)
        prompt = CRITIC_PROMPT_TEMPLATE.format(
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            theme=ctx.theme,
            duration_s=video.duration_s or 0,
            iteration=iteration,
            scenario_summary=scenario_summary,
            learning_block=LEARNING_CONTEXT_BLOCK.format(
                learning_context_prompt=ctx.learning_context_prompt,
            ),
            min_duration=ctx.channel_config.min_image_duration_s,
            min_score=ctx.channel_config.min_critic_score,
        )

        raw = await self._call_claude(prompt, system=CRITIC_SYSTEM, max_tokens=2048)
        data = self._parse_json(raw)

        score = data.get("global_score", 0)
        decision = data.get("decision", "iterate")

        if iteration >= ctx.channel_config.max_critic_iterations:
            decision = "approve"
            logger.info("Score %d/100 — itérations max atteintes, approbation forcée", score)
        elif score >= ctx.channel_config.min_critic_score:
            decision = "approve"

        async with AsyncSessionFactory() as session:
            report = CriticReport(
                video_id=video.id,
                iteration=iteration,
                decision=decision,
                global_score=score,
                feedback=data.get("feedback"),
                requested_changes=data.get("requested_changes", []),
            )
            session.add(report)

            from sqlalchemy import update
            await session.execute(
                update(Video)
                .where(Video.id == video.id)
                .values(status="approved" if decision == "approve" else "review")
            )
            await session.commit()
            await session.refresh(report)

        logger.info(
            "Critique itération %d : %d/100 → %s",
            iteration, score, decision
        )
        return report

    @staticmethod
    def _build_scenario_summary(scenario: Scenario) -> str:
        segments = scenario.segments or []
        lines = []
        for seg in segments[:5]:
            lines.append(
                f"- Segment {seg.get('order')}: {seg.get('title')} "
                f"({seg.get('duration_s')}s)"
            )
        if len(segments) > 5:
            lines.append(f"... et {len(segments) - 5} autres segments")
        return "\n".join(lines)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
