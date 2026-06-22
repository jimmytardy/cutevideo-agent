from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.beat_planner_prompt import BEAT_PLANNER_PHASE2_PROMPT, BEAT_PLANNER_SYSTEM
from agent.core.json_parse import parse_json_text
from agent.core.database import AsyncSessionFactory, AudioFile, Scenario
from agent.core.visual_beats import validate_beats_against_narration
from agent.core.visual_beats_prompt import build_visual_beats_prompt_context
from agent.skills.scenario.beat_timeline_split import (
    beat_slot_seconds,
    compute_target_beat_count,
    dynamic_max_beats,
    split_narration_into_beats,
    splits_to_visual_beats,
)
from agent.skills.video.montage_profile import short_beat_slot_s
from agent.skills.video.beat_timeline import word_segments_from_json

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)


class BeatPlannerAgent(BaseAgent):
    """Génère visual_beats post-TTS à partir des timestamps Whisper."""

    name = "beat_planner_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> Scenario:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id,
            {"scenario_id": str(scenario.id)},
            iteration=ctx.iteration,
        )
        try:
            updated = await self._plan_beats(ctx, scenario)
            await self.end_run(run, {"segments": len(updated.segments or [])})
            return updated
        except Exception as exc:
            await self.fail_run(run, exc)
            raise

    async def _plan_beats(self, ctx: "PipelineContext", scenario: Scenario) -> Scenario:
        async with AsyncSessionFactory() as session:
            audio_result = await session.execute(
                select(AudioFile)
                .where(AudioFile.project_id == ctx.project_id)
                .order_by(AudioFile.segment_order)
            )
            audio_files = list(audio_result.scalars().all())

        audio_by_order = {
            (af.segment_order or 0): af for af in audio_files if af.local_path
        }
        segments = list(scenario.segments or [])
        is_short = ctx.is_short_project
        vb = ctx.channel_config.visual_beats
        min_beats = vb.min_beats_per_short_segment if is_short else 3
        base_max_beats = vb.max_beats_per_segment
        min_img_s = float(
            ctx.channel_config.min_image_duration_short_s
            if is_short
            else ctx.channel_config.min_image_duration_s
        )
        slot_s = (
            short_beat_slot_s()
            if is_short
            else beat_slot_seconds(
                min_image_duration_s=min_img_s,
                max_static_shot_s=float(ctx.channel_config.max_static_shot_s),
            )
        )

        total_duration = 0.0
        for seg in segments:
            order = int(seg.get("order", 0))
            needs_voice = seg.get("needs_voice", True) is not False and bool(
                (seg.get("narration_text") or "").strip()
            )
            if not needs_voice:
                total_duration += float(seg.get("duration_s", 30))
                continue

            audio = audio_by_order.get(order)
            if not audio:
                logger.warning("Segment %d sans audio — beats inchangés", order)
                total_duration += float(seg.get("duration_s", 30))
                continue

            audio_duration = float(audio.duration_s or seg.get("duration_s", 30))
            words = word_segments_from_json(audio.word_timestamps)
            seg_max_beats = dynamic_max_beats(
                audio_duration,
                min_image_duration_s=min_img_s,
                base_max=base_max_beats,
            )
            target = compute_target_beat_count(
                audio_duration,
                beat_slot_s=slot_s,
                min_beats=min_beats,
                max_beats=seg_max_beats,
            )
            splits = split_narration_into_beats(
                str(seg.get("narration_text") or ""),
                words,
                audio_duration,
                target_beats=target,
                min_beats=min_beats,
                max_beats=seg_max_beats,
            )
            enriched = await self._enrich_beats_llm(ctx, seg, splits, is_short=is_short)
            seg["visual_beats"] = splits_to_visual_beats(splits, enriched)
            seg["duration_s"] = int(round(audio_duration))
            total_duration += audio_duration

            errors = validate_beats_against_narration(
                seg,
                vb_config=vb,
                is_short=is_short,
            )
            if errors:
                logger.warning("Validation beats segment %d : %s", order, errors)

        async with AsyncSessionFactory() as session:
            row = await session.get(Scenario, scenario.id)
            if row is None:
                raise RuntimeError(f"Scénario {scenario.id} introuvable")
            row.segments = segments
            row.total_duration_s = int(round(total_duration))
            await session.commit()
            await session.refresh(row)
            logger.info(
                "BeatPlanner — durée totale %.0f s, %d segments",
                total_duration,
                len(segments),
            )
            return row

    async def _enrich_beats_llm(
        self,
        ctx: "PipelineContext",
        segment: dict[str, Any],
        splits: list[Any],
        *,
        is_short: bool,
    ) -> list[dict[str, Any]]:
        if not splits:
            return []

        vb_ctx = build_visual_beats_prompt_context(
            ctx.channel_config.editorial_tone,
            ctx.theme_category,
            min_beats_short=ctx.channel_config.visual_beats.min_beats_per_short_segment,
            max_beats=ctx.channel_config.visual_beats.max_beats_per_segment,
            content_language=ctx.channel_config.content_language,
            min_diagram_duration_long=ctx.channel_config.visual_beats.min_diagram_duration_s,
            min_diagram_duration_short=ctx.channel_config.visual_beats.min_diagram_duration_short_s,
            is_short=is_short,
        )
        beats_input = [
            {
                "order": s.order,
                "phrase_anchor": s.phrase_anchor,
                "spoken_text": s.spoken_text,
                "duration_hint_s": s.duration_hint_s,
            }
            for s in splits
        ]
        prompt = BEAT_PLANNER_PHASE2_PROMPT.format(
            segment_order=segment.get("order", 0),
            theme=ctx.theme,
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            editorial_tone=ctx.channel_config.editorial_tone,
            segment_mood=segment.get("mood", "calme"),
            content_language=ctx.channel_config.content_language,
            narration_text=(segment.get("narration_text") or "")[:2000],
            beats_json=json.dumps(beats_input, ensure_ascii=False, indent=2),
            visual_beats_rules=vb_ctx["visual_beats_rules"],
        )
        raw = await self._call_claude(prompt, system=BEAT_PLANNER_SYSTEM, max_tokens=16384)
        data = self._parse_json(raw)
        beats = data.get("visual_beats") or []
        if not beats:
            return self._fallback_enriched(splits)
        return beats

    @staticmethod
    def _fallback_enriched(splits: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "order": s.order,
                "visual_type": "documentary_photo",
                "prompt": s.spoken_text[:200],
                "style_hint": "",
                "on_screen_text": "",
                "diagram_labels": [],
            }
            for s in splits
        ]

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        return parse_json_text(raw, "beat_planner_agent")
