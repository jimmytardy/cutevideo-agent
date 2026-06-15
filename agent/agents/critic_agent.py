from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, CriticReport, Scenario, Video
from agent.core.learning_context import LEARNING_CONTEXT_BLOCK, load_channel_context
from agent.core.llm_config import compact_learning_context

if TYPE_CHECKING:
    from agent.agents.video_analyst_agent import VideoAnalysis
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

CRITIC_SYSTEM = """Tu es un expert en production vidéo YouTube. Tu évalues objectivement les vidéos
produites par une IA et donnes des retours précis pour améliorer la qualité en fonction du thème
et du style éditorial de la chaîne. Tu retournes UNIQUEMENT du JSON valide."""

CRITIC_PROMPT_TEMPLATE = """Analyse cette vidéo et évalue-la sur 100.

CHAÎNE : {channel_name} ({theme_category})
{creative_brief_block}SUJET : {theme}
DURÉE : {duration_s} secondes
ITÉRATION : {iteration}

CONTENU DU SCÉNARIO (résumé) :
{scenario_summary}

{research_block}

{learning_block}

{video_analysis_block}

CRITÈRES D'ÉVALUATION (total 100 pts) :

RYTHME (20 pts)
- Durée minimale par image respectée (jamais < {min_duration}s) ?
- Schémas/infographies affichés assez longtemps pour être lus (>= {min_diagram_duration}s) ?
- Labels des schémas lisibles et bien positionnés (pas de flash < 3 s) ?
- Transitions fluides ?
- Cohérence tempo narration / images ?

VALEUR DU CONTENU (25 pts)
- La narration est pertinente et engageante pour le thème de la chaîne ?
- Fil conducteur clair ?

PRÉCISION FACTUELLE (10 pts)
- Les faits, dates et noms correspondent-ils au brief de recherche ?
- Aucune invention ou anachronisme flagrant ?

QUALITÉ VISUELLE (20 pts)
- Images pertinentes par rapport à la narration ?
- Variété des sources visuelles et des visual_type (pas 8× documentary_photo) ?
- Chaque concept verbal (mécanisme, comparaison, POV) a-t-il un visuel dédié (visual_beat) ?
- Présence de schémas/infographies pour segments explicatifs ?
- Labels des schémas en langue cohérente avec la narration, sans pseudo-texte illisible dans l'image ?
- Si images répétitives ou non illustratives : start_from = "media_agent" avec correction ciblée par beat

ACCROCHE ET STRUCTURE (15 pts)
- Hook fort les 30 premières secondes ?
- Chapitrage clair ?
- Conclusion mémorable ?

EXPRESSIVITÉ VOIX (10 pts)
- La voix varie-t-elle entre segments (énergie hook vs conclusion posée) ?
- Monotonie, manque d'emphase ou rythme plat ?
- Si score voix < {min_voice_score}/10 : start_from = "narrator_agent" avec corrections delivery_style

Retourne UNIQUEMENT ce JSON :
{{
  "global_score": 75,
  "start_from": "narrator_agent",
  "feedback": {{
    "rhythm": 16,
    "content_value": 20,
    "factual_accuracy": 8,
    "visual_quality": 16,
    "structure": 12,
    "voice_expressiveness": 7,
    "comments": "Commentaires détaillés ici"
  }},
  "decision": "approve",
  "requested_changes": []
}}

start_from (étape de reprise, obligatoire si decision = "iterate") :
- "research_agent" : erreurs factuelles majeures nécessitant une nouvelle recherche
- "scenario_agent" : l'angle éditorial, le hook ou la structure narrative est fondamentalement à revoir
- "media_agent"    : les images sont hors-sujet ou non pertinentes, mais la narration est solide
- "narrator_agent" : durée, rythme, monotonie vocale ou delivery_style à corriger
- "editor_agent"   : problème d'assemblage ou de timing uniquement, contenu et audio OK

"""

LONG_APPROVAL_RULES = """Si global_score < {min_score} : decision = "iterate" et requested_changes liste les agents à corriger :
[{{"agent": "editor_agent", "change_description": "Ralentir le segment X"}}]

Si global_score >= {min_score} : decision = "approve" et requested_changes = []"""

SHORT_APPROVAL_RULES = """RÈGLES D'APPROBATION (SHORT — les deux conditions sont obligatoires) :
- global_score >= {min_score}/100
- structure (Accroche & structure) >= {min_structure_score}/15
- decision = "approve" uniquement si les deux seuils sont atteints
- Sinon decision = "iterate" et requested_changes liste les corrections (priorité hook/structure si structure < {min_structure_score})"""

VIDEO_ANALYSIS_BLOCK_TEMPLATE = """ANALYSE VIDÉO GEMINI (vision directe de la vidéo finale) :
Score Gemini : {score}/100
Cohérence visuelle : {visual_coherence}/25 | Qualité sous-titres : {subtitle_quality}/25 | Rythme : {rhythm}/25
Expressivité vocale : {voice_expressiveness}/10
Résumé : {summary}
{issues_text}
IMPORTANT : Tiens compte de cette analyse réelle pour ajuster tes scores visuels et formuler des corrections précises."""


class CriticAgent(BaseAgent):
    """Agent 6 — Critique IA : analyse la vidéo et décide approve / iterate."""

    name = "critic_agent"

    async def run(  # type: ignore[override]
        self,
        ctx: "PipelineContext",
        video: Video,
        scenario: Scenario,
        iteration: int,
        video_analysis: "VideoAnalysis | None" = None,
        gemini_status: str = "missing_key",
    ) -> CriticReport:
        run = await self.start_run(
            ctx.project_id,
            {"video_id": str(video.id), "iteration": iteration},
            iteration=iteration,
        )
        try:
            report = await self._evaluate(ctx, video, scenario, iteration, video_analysis, gemini_status)
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
        video_analysis: "VideoAnalysis | None",
        gemini_status: str,
    ) -> CriticReport:
        scenario_summary = self._build_scenario_summary(scenario)
        learning = await load_channel_context(ctx.channel_id)
        learning_block = LEARNING_CONTEXT_BLOCK.format(
            learning_context_prompt="(voir bloc contexte chaîne ci-dessus)",
        )

        video_analysis_block = ""
        if video_analysis:
            issues_lines = []
            for issue in video_analysis.issues:
                sev = issue.get("severity", "?").upper()
                ts = issue.get("timestamp_s", 0)
                desc = issue.get("description", "")
                issues_lines.append(f"  [{sev}] {ts}s — {desc}")
            issues_text = (
                "Problèmes détectés :\n" + "\n".join(issues_lines)
                if issues_lines
                else "Aucun problème visuel détecté."
            )
            video_analysis_block = VIDEO_ANALYSIS_BLOCK_TEMPLATE.format(
                score=video_analysis.score,
                visual_coherence=video_analysis.visual_coherence,
                subtitle_quality=video_analysis.subtitle_quality,
                rhythm=video_analysis.rhythm,
                voice_expressiveness=video_analysis.voice_expressiveness,
                summary=video_analysis.summary,
                issues_text=issues_text,
            )

        from agent.agents.scenario_agent import _format_research_block
        from agent.core.config import load_agent_config

        research_block = _format_research_block(ctx.research_brief)
        brief = ctx.channel_config.creative_brief
        creative_brief_block = f"BRIEF CRÉATIF :\n{brief.strip()}\n\n" if brief and brief.strip() else ""
        pipeline_cfg = load_agent_config().get("pipeline", {})
        min_voice_score = int(pipeline_cfg.get("min_voice_score", 6))
        is_short = self._is_short_video(ctx, video)
        approval_rules = (
            SHORT_APPROVAL_RULES.format(
                min_score=ctx.channel_config.min_critic_score,
                min_structure_score=ctx.channel_config.min_short_structure_score,
            )
            if is_short
            else LONG_APPROVAL_RULES.format(min_score=ctx.channel_config.min_critic_score)
        )
        is_short = ctx.channel_config.production_mode == "shorts_only"
        min_diagram = (
            ctx.channel_config.visual_beats.min_diagram_duration_short_s
            if is_short
            else ctx.channel_config.visual_beats.min_diagram_duration_s
        )
        prompt = CRITIC_PROMPT_TEMPLATE.format(
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            creative_brief_block=creative_brief_block,
            theme=ctx.theme,
            duration_s=video.duration_s or 0,
            iteration=iteration,
            scenario_summary=scenario_summary,
            research_block=research_block,
            learning_block=learning_block,
            video_analysis_block=video_analysis_block,
            min_duration=ctx.channel_config.min_image_duration_s,
            min_diagram_duration=min_diagram,
            min_voice_score=min_voice_score,
        ) + approval_rules

        raw = await self._call_claude(
            prompt,
            system=CRITIC_SYSTEM,
            cacheable_context=compact_learning_context(learning),
        )
        data = self._parse_json(raw)

        # Extract start_from before feedback coercion so a null feedback never loses the routing hint.
        # Check top-level first, then inside raw feedback dict as LLM sometimes nests it there.
        raw_feedback = data.get("feedback")
        start_from_value = (
            data.get("start_from")
            or (isinstance(raw_feedback, dict) and raw_feedback.get("start_from"))
            or "media_agent"
        )
        feedback = raw_feedback if isinstance(raw_feedback, dict) else {}
        feedback["start_from"] = start_from_value
        data["feedback"] = feedback

        score = data.get("global_score", 0)
        structure_score = self._extract_structure_score(feedback)
        max_iterations = ctx.max_iterations_override or ctx.channel_config.max_critic_iterations
        decision = self._resolve_decision(
            global_score=score,
            structure_score=structure_score,
            is_short=is_short,
            iteration=iteration,
            max_iterations=max_iterations,
            min_critic_score=ctx.channel_config.min_critic_score,
            min_short_structure_score=ctx.channel_config.min_short_structure_score,
        )

        analysis_dict = self._build_video_analysis_dict(video_analysis, gemini_status)

        async with AsyncSessionFactory() as session:
            report = CriticReport(
                video_id=video.id,
                iteration=iteration,
                decision=decision,
                global_score=score,
                feedback=data.get("feedback"),
                requested_changes=data.get("requested_changes", []),
                video_analysis=analysis_dict,
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
            "Critique itération %d : %d/100 (structure %d/15) → %s (Gemini: %s)",
            iteration, score, structure_score, decision,
            f"{video_analysis.score}/100" if video_analysis else "N/A",
        )
        return report

    @staticmethod
    def _is_short_video(ctx: "PipelineContext", video: Video) -> bool:
        if ctx.channel_config.production_mode == "shorts_only":
            return True
        vtype = video.video_type or ""
        return vtype == "short_master" or vtype.startswith("short_")

    @staticmethod
    def _extract_structure_score(feedback: dict | list | None) -> int:
        if not isinstance(feedback, dict):
            return 0
        try:
            return int(feedback.get("structure") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _resolve_decision(
        global_score: int,
        structure_score: int,
        is_short: bool,
        iteration: int,
        max_iterations: int,
        min_critic_score: int,
        min_short_structure_score: int,
    ) -> str:
        if iteration >= max_iterations:
            logger.info(
                "Score %d/100 — itérations max atteintes (%d), approbation forcée",
                global_score,
                max_iterations,
            )
            return "approve"
        if global_score < min_critic_score:
            return "iterate"
        if is_short and structure_score < min_short_structure_score:
            logger.info(
                "Score %d/100 OK mais structure %d/15 < %d — itération requise",
                global_score,
                structure_score,
                min_short_structure_score,
            )
            return "iterate"
        return "approve"

    @staticmethod
    def _build_video_analysis_dict(
        video_analysis: "VideoAnalysis | None",
        gemini_status: str,
    ) -> dict:
        if video_analysis:
            data = video_analysis.to_dict()
            data["analysis_status"] = "ok"
            return data
        return {
            "analysis_status": gemini_status,
            "score": 0,
            "issues": [],
            "visual_coherence": 0,
            "subtitle_quality": 0,
            "rhythm": 0,
            "voice_expressiveness": 0,
            "summary": "",
        }

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
