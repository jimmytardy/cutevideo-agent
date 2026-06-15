from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Scenario
from agent.core.scenario_integrity import validate_merged_segments
from agent.core.visual_beats import parse_visual_beats
from agent.skills.media_sources.ai.prompt_builder import is_diagram_visual_type

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

DIAGRAM_SYSTEM = """Tu es spécialiste des schémas et infographies pour vidéos éducatives.
Enrichis les visual_beats explicatifs sans toucher à la narration.
Retourne UNIQUEMENT du JSON valide."""

DIAGRAM_PROMPT = """Enrichis les visual_beats de type diagramme/infographie du scénario.

SUJET : {theme}
LANGUE : {language}
MIN DIAGRAMME : {min_diagram}s

SEGMENTS AVEC BEATS DIAGRAMME :
{diagram_segments_json}

Pour chaque beat explicatif :
- Enrichir prompt (précis, description visuelle en {language}, sans mention de labels ni texte à afficher)
- diagram_labels cohérents (text ≤ 40 caractères, langue {language})
- duration_hint_s ≥ {min_diagram}
- Ajouter diagram_brief : {{ "layout": "...", "key_elements": [...], "fallback_visual_type": "infographic" }}

Retourne UNIQUEMENT :
{{
  "segments": [
    {{
      "order": 1,
      "visual_beats": [ ... uniquement les beats diagramme enrichis pour ce segment ... ]
    }}
  ]
}}

IMPORTANT : ne renvoie que les segments contenant des beats diagramme à enrichir.
Ne modifie pas narration_text, needs_voice, needs_music ni les autres champs."""


def _diagram_beats_by_order(segment: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Indexe les beats diagramme bruts (préserve diagram_brief et champs LLM)."""
    indexed: dict[int, dict[str, Any]] = {}
    for item in segment.get("visual_beats") or []:
        if not isinstance(item, dict):
            continue
        order = int(item.get("order", 0) or 0)
        visual_type = str(item.get("visual_type", "") or "")
        if order and is_diagram_visual_type(visual_type):
            indexed[order] = item
    return indexed


def merge_diagram_enrichment(
    original_segments: list[dict[str, Any]],
    llm_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fusionne les visual_beats diagramme enrichis dans le scénario d'origine.

    Préserve intégralement narration, voix, musique et tous les segments —
    seuls les beats de type diagramme sont remplacés quand le LLM en fournit.
    """
    llm_by_order: dict[int, dict[str, Any]] = {}
    for seg in llm_segments:
        order = int(seg.get("order", 0) or 0)
        if order:
            llm_by_order[order] = seg

    if len(llm_by_order) < len(original_segments):
        logger.warning(
            "Diagram specialist : LLM a renvoyé %d/%d segments — fusion chirurgicale",
            len(llm_by_order),
            len(original_segments),
        )

    merged: list[dict[str, Any]] = []
    for orig in original_segments:
        order = int(orig.get("order", 0) or 0)
        result = dict(orig)
        llm_seg = llm_by_order.get(order)
        if not llm_seg:
            merged.append(result)
            continue

        llm_diagram_by_order = _diagram_beats_by_order(llm_seg)
        if not llm_diagram_by_order:
            merged.append(result)
            continue

        new_beats: list[dict[str, Any]] = []
        for raw_beat in orig.get("visual_beats") or []:
            if not isinstance(raw_beat, dict):
                continue
            beat_order = int(raw_beat.get("order", 0) or 0)
            visual_type = str(raw_beat.get("visual_type", "") or "")
            if is_diagram_visual_type(visual_type) and beat_order in llm_diagram_by_order:
                new_beats.append(llm_diagram_by_order[beat_order])
            else:
                new_beats.append(raw_beat)
        result["visual_beats"] = new_beats
        merged.append(result)

    return merged


class DiagramSpecialistAgent(BaseAgent):
    """Enrichit les visual_beats diagrammes avant MediaAgent."""

    name = "diagram_specialist_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> Scenario:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id,
            {"scenario_id": str(scenario.id)},
            iteration=ctx.iteration,
        )
        try:
            updated = await self._enrich(ctx, scenario)
            await self.end_run(run, {"segments": len(updated.segments or [])})
            return updated
        except Exception as exc:
            await self.fail_run(run, exc)
            raise

    async def _enrich(self, ctx: "PipelineContext", scenario: Scenario) -> Scenario:
        segments = list(scenario.segments or [])
        diagram_segments: list[dict[str, Any]] = []
        has_diagram = False
        for seg in segments:
            beats = parse_visual_beats(seg)
            diagram_beats = [b for b in beats if is_diagram_visual_type(b.visual_type)]
            if diagram_beats:
                has_diagram = True
                diagram_segments.append({
                    "order": seg.get("order"),
                    "title": seg.get("title"),
                    "visual_beats": [b.model_dump() for b in diagram_beats],
                })

        if not has_diagram:
            return scenario

        min_diagram = ctx.channel_config.visual_beats.min_diagram_duration_s
        prompt = DIAGRAM_PROMPT.format(
            theme=ctx.theme,
            language=ctx.channel_config.content_language,
            min_diagram=min_diagram,
            diagram_segments_json=json.dumps(diagram_segments, ensure_ascii=False, indent=2),
        )
        raw = await self._call_claude(prompt, system=DIAGRAM_SYSTEM, max_tokens=4096)
        data = self._parse_json(raw)
        llm_segments = data.get("segments") or []
        new_segments = merge_diagram_enrichment(segments, llm_segments)
        validate_merged_segments(segments, new_segments)

        async with AsyncSessionFactory() as session:
            db_scenario = await session.get(Scenario, scenario.id)
            if db_scenario is None:
                raise RuntimeError(
                    f"Scénario {scenario.id} introuvable — enrichissement diagramme impossible"
                )
            db_scenario.segments = new_segments
            if scenario.total_duration_s is not None:
                db_scenario.total_duration_s = scenario.total_duration_s
            await session.commit()
            await session.refresh(db_scenario)
        logger.info("Diagram specialist — %d segments enrichis", len(diagram_segments))
        return db_scenario

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
