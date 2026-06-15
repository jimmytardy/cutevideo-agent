from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Scenario
from agent.core.json_parse import parse_json_text
from agent.core.scenario_integrity import validate_segment_count_preserved

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

HOOK_OPTIMIZABLE_KEYS: tuple[str, ...] = (
    "narration_text",
    "delivery_style",
    "visual_beats",
    "on_screen_text",
    "search_keywords",
)

HOOK_SYSTEM = """Tu optimises uniquement le segment hook (order=1) d'une vidéo éducative.
Storytelling, rythme rapide, question rhétorique obligatoire dans les 15 premières secondes de narration.
Retourne UNIQUEMENT du JSON valide (guillemets doubles échappés dans les chaînes, pas de commentaires)."""

HOOK_PROMPT = """Optimise le segment hook (order=1) pour maximiser l'accroche.

SUJET : {theme}
LANGUE : {language}

CHAMPS HOOK À OPTIMISER :
{hook_json}

Règles impératives :
- narration_text : storytelling vivant, question rhétorique dans les ~15 premières secondes
- delivery_style : pace "fast", emotion engageante, emphasis_words sur mots clés
- visual_beats : 3 à 5 beats denses, duration_hint_s ≤ 6 (sauf diagrammes ≥ {min_diagram}s)
- Interdit un seul beat photo/vidéo pour tout le hook
- Chaque phrase_anchor = extrait exact de narration_text

Retourne UNIQUEMENT un objet JSON avec ces clés (pas de media_validation, pas de métadonnées) :
narration_text, delivery_style, visual_beats, on_screen_text, search_keywords."""

HOOK_RETRY_PROMPT = """Ta réponse précédente n'était pas du JSON valide ({error}).
Régénère UNIQUEMENT l'objet JSON des champs optimisés listés ci-dessous.
Échappe tous les guillemets doubles internes avec \\".

CHAMPS HOOK À OPTIMISER :
{hook_json}"""


class HookOptimizerAgent(BaseAgent):
    """Optimise le segment 1 (hook) avant recherche média."""

    name = "hook_optimizer_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> Scenario:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id,
            {"scenario_id": str(scenario.id)},
            iteration=ctx.iteration,
        )
        try:
            updated = await self._optimize(ctx, scenario)
            segments = updated.segments or []
            orders = [int(s.get("order", 0) or 0) for s in segments]
            await self.end_run(
                run,
                {
                    "new_scenario_id": str(updated.id),
                    "base_scenario_id": str(scenario.id),
                    "segments_count": len(segments),
                    "segment_orders": orders,
                },
            )
            return updated
        except Exception as exc:
            await self.fail_run(run, exc)
            raise

    async def _optimize(self, ctx: "PipelineContext", scenario: Scenario) -> Scenario:
        segments = list(scenario.segments or [])
        hook = next((s for s in segments if int(s.get("order", 0)) == 1), None)
        if not hook or not hook.get("needs_voice", True):
            return scenario

        min_diagram = ctx.channel_config.visual_beats.min_diagram_duration_s
        hook_subset = _extract_hook_subset(hook)
        hook_json = json.dumps(hook_subset, ensure_ascii=False, indent=2)
        prompt = HOOK_PROMPT.format(
            theme=ctx.theme,
            language=ctx.channel_config.content_language,
            hook_json=hook_json,
            min_diagram=min_diagram,
        )
        raw = await self._call_claude(prompt, system=HOOK_SYSTEM, max_tokens=4096)
        try:
            optimized = self._parse_json(raw)
        except ValueError as exc:
            logger.warning("JSON hook invalide, retry : %s", exc)
            retry_prompt = HOOK_RETRY_PROMPT.format(error=exc, hook_json=hook_json)
            raw = await self._call_claude(retry_prompt, system=HOOK_SYSTEM, max_tokens=4096)
            optimized = self._parse_json(raw)

        new_segments: list[dict[str, Any]] = []
        for seg in segments:
            if int(seg.get("order", 0)) == 1:
                new_segments.append(_merge_hook(seg, optimized))
            else:
                new_segments.append(seg)

        validate_segment_count_preserved(
            segments,
            new_segments,
            context="hook_optimizer_agent",
        )

        async with AsyncSessionFactory() as session:
            new_scenario = Scenario(
                project_id=ctx.project_id,
                segments=new_segments,
                total_duration_s=scenario.total_duration_s,
                iteration=ctx.iteration,
            )
            session.add(new_scenario)
            await session.commit()
            await session.refresh(new_scenario)
        logger.info("Hook optimisé — %d visual_beats", len(new_segments[0].get("visual_beats") or []))
        return new_scenario

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        return parse_json_text(raw, "hook_optimizer_agent", repair_fn=None)


def _extract_hook_subset(hook: dict[str, Any]) -> dict[str, Any]:
    return {key: hook[key] for key in HOOK_OPTIMIZABLE_KEYS if key in hook}


def _merge_hook(segment: dict[str, Any], optimized: dict[str, Any]) -> dict[str, Any]:
    merged = dict(segment)
    for key in HOOK_OPTIMIZABLE_KEYS:
        if key in optimized:
            merged[key] = optimized[key]
    merged["order"] = 1
    return merged
