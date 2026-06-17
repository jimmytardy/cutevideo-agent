from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import update

from agent.agents.scenario_agent import _format_research_block
from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Project, Scenario
from agent.core.scenario_integrity import validate_segment_count_preserved

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

REVISION_SYSTEM = """Tu es un agent de révision expert en modification chirurgicale de scénarios vidéo.

Ta spécialité : appliquer des corrections précises demandées par un critique, en modifiant
UNIQUEMENT ce qui est problématique. Tu ne régénères jamais de zéro — tu patches le scénario existant.

Règles absolues :
- Garde la structure globale et le nombre de segments si possible
- Modifie seulement les segments/champs concernés par les corrections
- Retourne TOUJOURS le scénario complet (tous les segments, même non modifiés)
- Produis uniquement du JSON valide, sans texte avant ni après"""

REVISION_PROMPT = """Applique les corrections ci-dessous sur le scénario existant.

SUJET : {theme}
{duration_header}
TYPE DE CORRECTION : {start_from_label}

SCÉNARIO ACTUEL ({segment_count} segments — {current_duration}s au total) :
{scenario_json}

CORRECTIONS DEMANDÉES PAR LE CRITIQUE :
{changes_list}

CORRESPONDANCE corrections → champs à modifier :
- "scenario_agent" / "scénario" / "contenu" / "angle" → title (si besoin), narration_text, hook_type, on_screen_text
- "beat_planner_agent" / "beats" / "découpage" / "phrase_anchor" → signaler dans revision_notes (regénération beat_planner gérée par l'orchestrateur)
- "media_agent" / "médias" / "images" → search_keywords si segment avec voix ; visual_beats uniquement si needs_voice false (beats voix regénérés par beat_planner)
- "narrator_agent" / "narration" / "voix" / "durée" → narration_text, duration_s, delivery_style
- "editor_agent" / "montage" / "timing" → duration_s uniquement (sans toucher narration_text)
- Erreurs factuelles majeures → signaler dans revision_notes (reprise research_agent gérée par l'orchestrateur)

{media_library_block}

RÈGLES BIBLIOTHÈQUE MÉDIA :
- Les images déjà générées restent en pool réutilisable — ne regénère que les beats explicitement concernés
- Segments avec voix : corrections images → search_keywords uniquement (visual_beats regénérés par beat_planner)
- Segments sans voix : modifier visual_beats directement si nécessaire

{research_block}

RÈGLES IMPÉRATIVES :
1. Ne modifie PAS les segments non concernés — copie-les à l'identique
{duration_rule_2}
3. Pour une correction d'images sur segment voix : mets à jour search_keywords ; ne modifie pas visual_beats (générés post-TTS)
4. Conserve TOUS les champs existants (order, hook_type, delivery_style, mood, strip_source_audio, needs_music, etc.)

{visual_beats_block}

Retourne UNIQUEMENT ce JSON :
{{
  "title": "titre (identique sauf si la correction demande un changement d'angle)",
  "description": "description courte",
  "segments": [
    {{
      "order": 1,
      "title": "...",
      "duration_s": 20,
      "needs_voice": true,
      "needs_music": true,
      "narration_text": "...",
      "on_screen_text": "...",
      "search_keywords": ["kw fr", "kw en"],
      "source_hint": ["pexels"],
      "mood": "energique",
      "strip_source_audio": true,
      "hook_type": "fait_surprenant",
      "delivery_style": {{"pace": "fast", "emotion": "playful", "azure_style": "cheerful", "emphasis_words": []}},
      "visual_beats": []
    }}
  ],
  "total_duration_s": {total_duration_hint},
  "revision_notes": "Résumé en 1-2 phrases de ce qui a été modifié et pourquoi"
}}"""

_DURATION_HEADER_SHORT = (
    "PLAGE SHORT : {min_short_duration_s}–{max_short_duration_s} s "
    "(indicatif, durée réelle post-TTS)"
)
_DURATION_HEADER_LONG = "DURÉE CIBLE : {target_duration_s}s"

_DURATION_RULE_SHORT = """2. Pour une correction de durée sur un short :
   → Condense ou étends narration_text pour viser la plage {min_short_duration_s}–{max_short_duration_s} s
   → total_duration_s indicatif (durée réelle fixée après synthèse vocale) — pas de valeur exacte imposée"""

_DURATION_RULE_LONG = """2. Pour une correction de durée totale (ex : "réduire de 240s à 60s") :
   → Réduis proportionnellement duration_s de chaque segment
   → Condense narration_text en gardant UNIQUEMENT les faits essentiels
   → Le total_duration_s final DOIT être exactement {target_duration_s}"""

_START_FROM_LABELS: dict[str, str] = {
    "scenario_agent": "Refonte du contenu/angle éditorial",
    "beat_planner_agent": "Correction du découpage visuel (beats)",
    "media_agent": "Remplacement des sources visuelles",
    "narrator_agent": "Correction de la narration/durée",
    "editor_agent": "Ajustement du montage/timing",
}


class RevisionAgent(BaseAgent):
    """Spécialiste de la révision chirurgicale — patche le scénario selon les corrections du critique.

    Ne régénère jamais un scénario from scratch : il applique des modifications ciblées
    sur le scénario existant, en préservant tout ce qui n'est pas concerné par les corrections.
    """

    name = "revision_agent"

    async def run(self, ctx: "PipelineContext", current_scenario: Scenario) -> Scenario:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id,
            {
                "base_scenario_id": str(current_scenario.id),
                "start_from": ctx.critic_start_from,
                "changes_count": len(ctx.critic_feedback or []),
                "iteration": ctx.iteration,
            },
            iteration=ctx.iteration,
        )
        try:
            scenario = await self._revise_scenario(ctx, current_scenario)
            await self.end_run(run, {"new_scenario_id": str(scenario.id), "segments": len(scenario.segments or [])})
            return scenario
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _revise_scenario(self, ctx: "PipelineContext", current_scenario: Scenario) -> Scenario:
        segments = current_scenario.segments or []
        start_from = ctx.critic_start_from or "scenario_agent"
        start_from_label = _START_FROM_LABELS.get(start_from, start_from)

        changes_lines = [
            f"- [{c.get('agent', '?')}] {c.get('change_description', '')}"
            for c in (ctx.critic_feedback or [])
        ]
        changes_list = "\n".join(changes_lines) if changes_lines else "Aucune correction spécifique."

        scenario_payload = {
            "segments": segments,
            "total_duration_s": current_scenario.total_duration_s or ctx.target_duration_seconds,
        }
        scenario_json = json.dumps(scenario_payload, ensure_ascii=False, indent=2)

        from agent.skills.media.media_library import count_pool, pool_summary_for_prompt

        pool_count = await count_pool(ctx.project_id)
        media_library_block = pool_summary_for_prompt(pool_count)

        from agent.core.visual_beats_prompt import build_revision_visual_beats_block

        is_short = (
            ctx.is_short_project
            or ctx.channel_config.production_mode == "shorts_only"
        )
        has_no_voice_segment = any(
            seg.get("needs_voice") is False for seg in segments if isinstance(seg, dict)
        )
        visual_beats_block = (
            build_revision_visual_beats_block(
                ctx.channel_config.editorial_tone,
                ctx.theme_category,
            )
            if has_no_voice_segment
            else ""
        )

        min_short = ctx.channel_config.min_short_duration_s
        max_short = ctx.channel_config.max_short_duration_s
        if is_short:
            duration_header = _DURATION_HEADER_SHORT.format(
                min_short_duration_s=min_short,
                max_short_duration_s=max_short,
            )
            duration_rule_2 = _DURATION_RULE_SHORT.format(
                min_short_duration_s=min_short,
                max_short_duration_s=max_short,
            )
            total_duration_hint = f"indicatif entre {min_short} et {max_short}"
        else:
            duration_header = _DURATION_HEADER_LONG.format(
                target_duration_s=ctx.target_duration_seconds,
            )
            duration_rule_2 = _DURATION_RULE_LONG.format(
                target_duration_s=ctx.target_duration_seconds,
            )
            total_duration_hint = str(ctx.target_duration_seconds)

        prompt = REVISION_PROMPT.format(
            theme=ctx.theme,
            duration_header=duration_header,
            duration_rule_2=duration_rule_2,
            total_duration_hint=total_duration_hint,
            start_from_label=start_from_label,
            segment_count=len(segments),
            current_duration=current_scenario.total_duration_s or 0,
            scenario_json=scenario_json,
            changes_list=changes_list,
            research_block=_format_research_block(ctx.research_brief),
            media_library_block=media_library_block,
            visual_beats_block=visual_beats_block,
        )

        raw = await self._call_claude(prompt, system=REVISION_SYSTEM, max_tokens=8192)
        data = self._parse_json(raw)

        new_segments = data.get("segments", segments)
        new_duration = data.get("total_duration_s", ctx.target_duration_seconds)

        validate_segment_count_preserved(
            segments,
            new_segments,
            context="revision_agent",
        )

        async with AsyncSessionFactory() as session:
            new_scenario = Scenario(
                project_id=ctx.project_id,
                segments=new_segments,
                total_duration_s=new_duration,
                iteration=ctx.iteration,
            )
            session.add(new_scenario)

            if data.get("title"):
                await session.execute(
                    update(Project)
                    .where(Project.id == ctx.project_id)
                    .values(title=data["title"])
                )

            await session.commit()
            await session.refresh(new_scenario)

        notes = data.get("revision_notes", "")
        logger.info(
            "Révision %s — %d segments, %ds : %s",
            start_from,
            len(new_segments),
            new_duration,
            notes[:120] if notes else "—",
        )
        return new_scenario

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
