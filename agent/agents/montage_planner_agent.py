from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, AudioFile, MediaAsset, MontagePlan, Scenario
from agent.core.json_parse import parse_json_text
from agent.core.montage_plan import (
    BeatClipPlan,
    EffectiveBeat,
    MontagePlanData,
    SegmentMontagePlan,
)
from agent.core.visual_beats import (
    effective_min_duration,
    is_diagram_beat,
    parse_visual_beats,
)
from agent.skills.media.clip_source_analyzer import clip_metadata_from_dict
from agent.skills.video.beat_timeline import word_segments_from_json
from agent.skills.video.montage_profile import is_short_montage, long_pacing_config
from agent.skills.video.pacing_director import pacing_hints_from_dict
from agent.skills.video.diagram_overlay_renderer import (
    render_diagram_overlay_png,
    render_single_text_overlay_png,
)
from agent.skills.video.diagram_text_layout import analyze_diagram_text_layout
from agent.skills.video.filter_graph_builder import profile_from_config
from agent.skills.video.montage_decisions import (
    load_transition_config,
    resolve_motion_style,
    resolve_overlay_mode,
    resolve_text_animation,
    resolve_transition,
)
from agent.skills.video.video_style_config import resolve_max_visual_hold_s
from agent.skills.video.clip_timeline_normalize import (
    TimelineClipDraft,
    expand_timeline_to_clip_drafts,
    extend_last_clip_to_match_audio,
    validate_visual_audio_alignment,
)
from agent.skills.video.trim_selector import select_trim_window

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """Tu adaptes la structure visuelle (effective_beats) d'un segment
selon les médias disponibles. La narration ne change pas.
Retourne UNIQUEMENT du JSON valide."""

PLANNER_PROMPT = """Segment {segment_order} — adapter les beats visuels aux médias disponibles.

Les beats sont déjà calibrés post-TTS (beat_planner). Ne re-découpe pas la narration.
Fusionne uniquement si une vidéo longue couvre plusieurs beats consécutifs.

Narration (extrait) : {narration_excerpt}
Durée audio : {audio_duration_s:.1f}s
Beats scénario : {beats_json}
Médias disponibles : {assets_json}

Règles :
- Fusionner beats si une vidéo longue couvre plusieurs moments
- Supprimer beats sans média si durée < 3s
- max {max_static_shot_s}s par plan (sous-clips gérés en aval)
- Durée totale = {audio_duration_s:.1f}s
- Ne pas changer phrase_anchor ni le nombre de beats sans raison média

Retourne :
{{
  "effective_beats": [
    {{
      "order": 1,
      "phrase_anchor": "...",
      "visual_type": "...",
      "adaptation": "unchanged",
      "source_beat_orders": [1],
      "transition_hint": "",
      "motion_hint": ""
    }}
  ],
  "adaptation_notes": "..."
}}"""


class MontagePlannerAgent(BaseAgent):
    """Planifie le montage beat-aware avant EditorAgent."""

    name = "montage_planner_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> MontagePlan:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id,
            {"scenario_id": str(scenario.id)},
            iteration=ctx.iteration,
        )
        try:
            plan_row = await self._build_and_persist(ctx, scenario)
            segments = plan_row.plan_data.get("segments", []) if plan_row.plan_data else []
            total_clips = sum(len(s.get("clips") or []) for s in segments)
            total_beats = sum(len(s.get("effective_beats") or []) for s in segments)
            adaptations = sum(
                1
                for s in segments
                for b in (s.get("effective_beats") or [])
                if b.get("adaptation") not in (None, "", "unchanged")
            )
            await self.end_run(run, {
                "plan_id": str(plan_row.id),
                "segments": len(segments),
                "clips": total_clips,
                "beats": total_beats,
                "adaptations": adaptations,
            })
            return plan_row
        except Exception as exc:
            await self.fail_run(run, exc)
            raise

    async def _build_and_persist(self, ctx: "PipelineContext", scenario: Scenario) -> MontagePlan:
        media_assets, audio_files = await self._load_assets(
            ctx.project_id, iteration=ctx.iteration
        )
        plan_data = await self.build_montage_plan_data(
            ctx, scenario, media_assets, audio_files,
        )

        async with AsyncSessionFactory() as session:
            row = MontagePlan(
                project_id=ctx.project_id,
                iteration=ctx.iteration,
                plan_data=plan_data.to_db_dict(),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        logger.info("MontagePlan — %d segments planifiés", len(plan_data.segments))
        return row

    @staticmethod
    async def build_montage_plan_data(
        ctx: "PipelineContext",
        scenario: Scenario,
        media_assets: list[MediaAsset],
        audio_files: list[AudioFile],
    ) -> MontagePlanData:
        segment_plans: list[SegmentMontagePlan] = []
        planner = MontagePlannerAgent()

        for seg in scenario.segments or []:
            order = int(seg.get("order", 0))
            seg_plan = await planner._plan_segment(ctx, seg, order, media_assets, audio_files)
            if seg_plan.clips:
                segment_plans.append(seg_plan)

        return MontagePlanData(
            project_id=ctx.project_id,
            iteration=ctx.iteration,
            segments=segment_plans,
            planner_notes="",
            is_vertical=is_short_montage(ctx),
        )

    @staticmethod
    async def _load_assets(
        project_id: uuid.UUID,
        *,
        iteration: int,
    ) -> tuple[list[MediaAsset], list[AudioFile]]:
        async with AsyncSessionFactory() as session:
            ma = await session.execute(
                select(MediaAsset)
                .where(
                    MediaAsset.project_id == project_id,
                    MediaAsset.selected == True,
                    MediaAsset.iteration == iteration,
                )
                .order_by(MediaAsset.segment_order, MediaAsset.beat_index)
            )
            af = await session.execute(
                select(AudioFile)
                .where(
                    AudioFile.project_id == project_id,
                    AudioFile.iteration == iteration,
                )
                .order_by(AudioFile.segment_order)
            )
            return list(ma.scalars().all()), list(af.scalars().all())

    async def _plan_segment(
        self,
        ctx: "PipelineContext",
        seg: dict[str, Any],
        order: int,
        media_assets: list[MediaAsset],
        audio_files: list[AudioFile],
    ) -> SegmentMontagePlan:
        beats = parse_visual_beats(seg)
        segment_mood = str(seg.get("mood", "calme"))
        is_short = is_short_montage(ctx)
        audio = next((af for af in audio_files if (af.segment_order or 0) == order), None)
        audio_duration = float(
            audio.duration_s if audio and audio.duration_s else seg.get("duration_s", 30)
        )

        if not beats:
            if seg.get("visual_optional") and audio:
                clip = BeatClipPlan(
                    beat_order=1,
                    source_beat_orders=[0],
                    asset_path="",
                    asset_type="color",
                    timeline_start_s=0.0,
                    timeline_end_s=audio_duration,
                    on_screen_text=str(seg.get("on_screen_text", "")),
                    visual_type="text_card",
                )
                enriched = await self._enrich_clips(
                    ctx, order, [clip], segment_mood, is_short,
                    narration_excerpt=(seg.get("narration_text") or "")[:500],
                )
                return SegmentMontagePlan(
                    segment_order=order,
                    clips=enriched,
                    segment_mood=segment_mood,
                )
            return SegmentMontagePlan(segment_order=order)

        seg_assets = sorted(
            [a for a in media_assets if (a.segment_order or 0) == order],
            key=lambda a: (a.beat_index or 0, a.created_at),
        )
        asset_by_beat: dict[int, MediaAsset] = {}
        for a in seg_assets:
            if a.beat_index and a.local_path and Path(a.local_path).exists():
                asset_by_beat[a.beat_index] = a

        words = word_segments_from_json(audio.word_timestamps if audio else None)

        effective_beats, adaptation_notes = await self._resolve_effective_beats(
            ctx, seg, order, beats, seg_assets, audio_duration,
        )

        def min_for_beat(beat: Any) -> float:
            return effective_min_duration(beat, is_short=is_short, config=ctx.channel_config)

        beat_objs = []
        for i, eb in enumerate(effective_beats):
            src = eb.source_beat_orders[0] if eb.source_beat_orders else eb.order
            match = next((b for b in beats if b.order == src), beats[min(i, len(beats) - 1)])
            beat_objs.append(match)

        image_paths = []
        for eb in effective_beats:
            src = eb.source_beat_orders[0] if eb.source_beat_orders else eb.order
            asset = asset_by_beat.get(src)
            if asset and asset.local_path:
                image_paths.append(asset.local_path)
            elif seg_assets and seg_assets[0].local_path:
                image_paths.append(seg_assets[0].local_path)

        timeline = compute_beat_timeline(
            beat_objs,
            words,
            audio_duration,
            min_duration_for_beat=min_for_beat,
            image_paths=image_paths,
        )

        needs_voice = seg.get("needs_voice", True) is not False and bool(
            (seg.get("narration_text") or "").strip()
        )
        strip_source = bool(seg.get("strip_source_audio", needs_voice))
        drafts: list[TimelineClipDraft] = []
        max_hold = resolve_max_visual_hold_s(is_short=is_short)
        max_static = min(float(ctx.channel_config.max_static_shot_s), max_hold)
        for i, entry in enumerate(timeline):
            src_order = entry.beat.order
            asset = asset_by_beat.get(src_order)
            if not asset or not asset.local_path:
                asset = seg_assets[i] if i < len(seg_assets) else (seg_assets[0] if seg_assets else None)
            if not asset or not asset.local_path:
                continue
            beat_duration = max(entry.end_s - entry.start_s, 0.5)
            meta = clip_metadata_from_dict(
                asset.clip_metadata if isinstance(asset.clip_metadata, dict) else None
            )
            source_dur = float(asset.duration_s or beat_duration)
            is_video = (asset.asset_type or "image") == "video"
            eb = effective_beats[i] if i < len(effective_beats) else None
            visual_type = (
                eb.visual_type if eb else entry.beat.visual_type
            )

            trim_start, trim_end = 0.0, None
            trim_reason = ""
            if is_video:
                sel = select_trim_window(
                    source_duration_s=source_dur,
                    target_duration_s=beat_duration,
                    phrase_anchor=entry.beat.phrase_anchor,
                    visual_type=entry.beat.visual_type,
                    clip_metadata=meta,
                )
                trim_start = sel.start_s
                trim_end = sel.end_s
                trim_reason = sel.reason

            drafts.append(
                TimelineClipDraft(
                    beat_order=i + 1,
                    source_beat_orders=(
                        effective_beats[i].source_beat_orders if i < len(effective_beats)
                        else [entry.beat.order]
                    ),
                    asset_path=asset.local_path,
                    asset_type="video" if is_video else "image",
                    timeline_start_s=entry.start_s,
                    timeline_end_s=entry.end_s,
                    source_trim_start_s=trim_start,
                    source_trim_end_s=trim_end,
                    trim_reason=trim_reason,
                    on_screen_text=entry.on_screen_text or entry.beat.on_screen_text,
                    visual_type=visual_type,
                    strip_source_audio=strip_source,
                )
            )

        expanded_drafts = expand_timeline_to_clip_drafts(
            drafts,
            max_static_shot_s=max_static,
        )
        clips: list[BeatClipPlan] = [
            BeatClipPlan(
                beat_order=d.beat_order,
                source_beat_orders=d.source_beat_orders,
                asset_path=d.asset_path,
                asset_type=d.asset_type,  # type: ignore[arg-type]
                timeline_start_s=d.timeline_start_s,
                timeline_end_s=d.timeline_end_s,
                source_trim_start_s=d.source_trim_start_s,
                source_trim_end_s=d.source_trim_end_s,
                trim_reason=d.trim_reason,
                on_screen_text=d.on_screen_text,
                visual_type=d.visual_type,
                strip_source_audio=d.strip_source_audio,
            )
            for d in expanded_drafts
        ]
        clips = extend_last_clip_to_match_audio(clips, audio_duration)
        validate_visual_audio_alignment(clips, audio_duration)

        enriched = await self._enrich_clips(
            ctx,
            order,
            clips,
            segment_mood,
            is_short,
            effective_beats=effective_beats,
            beat_objs=beat_objs,
            narration_excerpt=(seg.get("narration_text") or "")[:500],
        )

        return SegmentMontagePlan(
            segment_order=order,
            effective_beats=effective_beats,
            clips=enriched,
            adaptation_notes=adaptation_notes,
            segment_mood=segment_mood,
        )

    async def _enrich_clips(
        self,
        ctx: "PipelineContext",
        segment_order: int,
        clips: list[BeatClipPlan],
        segment_mood: str,
        is_short: bool,
        *,
        effective_beats: list[EffectiveBeat] | None = None,
        beat_objs: list[Any] | None = None,
        narration_excerpt: str = "",
    ) -> list[BeatClipPlan]:
        from agent.core.api_keys import fetch_api_key

        gemini_ctx = await fetch_api_key(
            ctx.user_id, "gemini", purpose="diagram_layout", tier="free"
        )
        gemini_api_key = gemini_ctx.key
        trans_cfg = load_transition_config(is_short=is_short)
        mood_transitions = (
            {}
            if is_short
            else {
                str(k).lower(): str(v)
                for k, v in (long_pacing_config().get("mood_transitions") or {}).items()
            }
        )
        pacing = pacing_hints_from_dict(getattr(ctx, "pacing_hints", None))
        profile = profile_from_config(is_short)
        overlay_dir = Path(f"./tmp/{ctx.project_id}/overlays")
        overlay_dir.mkdir(parents=True, exist_ok=True)
        default_transition = resolve_transition(
            segment_mood=segment_mood,
            prev_visual_type="",
            next_visual_type=clips[0].visual_type if clips else "",
            default_transition="fade",
        )

        enriched: list[BeatClipPlan] = []
        for i, clip in enumerate(clips):
            eb = effective_beats[i] if effective_beats and i < len(effective_beats) else None
            beat_obj = beat_objs[i] if beat_objs and i < len(beat_objs) else None
            pacing_hint = pacing.get((segment_order, clip.beat_order))
            hook_type = ""
            motion_hint = (
                (pacing_hint.motion_hint if pacing_hint else "")
                or (eb.motion_hint if eb else "")
            )
            overlay_mode = resolve_overlay_mode(
                clip.visual_type,
                clip.on_screen_text,
                hook_type=hook_type,
            )
            text_animation = resolve_text_animation(clip.visual_type, hook_type=hook_type)
            motion_style = resolve_motion_style(
                clip.visual_type,
                clip.asset_type,
                motion_hint=motion_hint,
                index=i,
                is_short=is_short,
                hook_type=hook_type,
            )

            text_layout: list[dict[str, Any]] = []
            overlay_path = ""

            if overlay_mode == "svg_overlay" and beat_obj and is_diagram_beat(beat_obj):
                labels = beat_obj.resolved_diagram_labels()
                if labels and clip.asset_path and Path(clip.asset_path).exists():
                    layout = await analyze_diagram_text_layout(
                        Path(clip.asset_path),
                        labels,
                        narration_excerpt=narration_excerpt,
                        language=ctx.channel_config.content_language,
                        visual_type=beat_obj.visual_type,
                        vertical=is_short,
                        width=profile.width,
                        height=profile.height,
                        api_key=gemini_api_key,
                    )
                    if layout:
                        text_layout = [
                            {
                                "text": p.text,
                                "x_norm": p.x_norm,
                                "y_norm": p.y_norm,
                                "fontsize": p.fontsize,
                                "box": p.box,
                            }
                            for p in layout
                        ]
                        png_path = overlay_dir / f"seg{segment_order:02d}_beat{i:02d}.png"
                        render_diagram_overlay_png(
                            profile.width,
                            profile.height,
                            layout,
                            png_path,
                        )
                        overlay_path = str(png_path)
            elif overlay_mode == "ass_overlay" and clip.on_screen_text:
                overlay_path = ""
            elif overlay_mode == "drawtext" and clip.on_screen_text:
                png_path = overlay_dir / f"seg{segment_order:02d}_beat{i:02d}_txt.png"
                try:
                    render_single_text_overlay_png(
                        profile.width,
                        profile.height,
                        clip.on_screen_text,
                        png_path,
                        vertical=is_short,
                        visual_type=clip.visual_type,
                    )
                    overlay_mode = "svg_overlay"
                    overlay_path = str(png_path)
                except ValueError:
                    overlay_mode = "drawtext"

            transition_out = "fade"
            if i < len(clips) - 1:
                next_clip = clips[i + 1]
                next_eb = (
                    effective_beats[i + 1]
                    if effective_beats and i + 1 < len(effective_beats)
                    else None
                )
                transition_hint = (
                    (pacing_hint.transition_hint if pacing_hint else "")
                    or (eb.transition_hint if eb else "")
                )
                if is_short and segment_mood.lower() == "energique" and not transition_hint:
                    transition_hint = "pixelize"
                if not transition_hint and segment_mood.lower() in mood_transitions:
                    transition_hint = mood_transitions[segment_mood.lower()]
                transition_out = resolve_transition(
                    segment_mood=segment_mood,
                    prev_visual_type=clip.visual_type,
                    next_visual_type=next_clip.visual_type,
                    default_transition=default_transition,
                    transition_hint=transition_hint,
                    is_chapter_break=i == 0 and segment_order > 1,
                    hook_type=hook_type,
                    config=trans_cfg,
                )

            enriched.append(clip.model_copy(update={
                "motion_style": motion_style,
                "overlay_mode": overlay_mode,
                "overlay_asset_path": overlay_path,
                "text_layout": text_layout,
                "text_animation": text_animation if overlay_mode == "ass_overlay" else "",
                "transition_out": transition_out,
                "transition_duration_s": trans_cfg.duration_s,
            }))
        return enriched

    async def _resolve_effective_beats(
        self,
        ctx: "PipelineContext",
        seg: dict[str, Any],
        order: int,
        beats: list[Any],
        seg_assets: list[MediaAsset],
        audio_duration: float,
    ) -> tuple[list[EffectiveBeat], str]:
        default = [
            EffectiveBeat(
                order=b.order,
                phrase_anchor=b.phrase_anchor,
                visual_type=b.visual_type,
                on_screen_text=b.on_screen_text,
                adaptation="unchanged",
                source_beat_orders=[b.order],
            )
            for b in beats
        ]
        if not seg_assets:
            return default, ""

        assets_json = [
            {
                "beat_index": a.beat_index,
                "asset_type": a.asset_type,
                "duration_s": a.duration_s,
                "path": a.local_path,
            }
            for a in seg_assets
        ]
        try:
            prompt = PLANNER_PROMPT.format(
                segment_order=order,
                narration_excerpt=(seg.get("narration_text") or "")[:400],
                audio_duration_s=audio_duration,
                beats_json=json.dumps([b.model_dump() for b in beats], ensure_ascii=False),
                assets_json=json.dumps(assets_json, ensure_ascii=False),
                max_static_shot_s=ctx.channel_config.max_static_shot_s,
            )
            raw = await self._call_claude(prompt, system=PLANNER_SYSTEM, max_tokens=16384)
            data = self._parse_json(raw)
            raw_beats = data.get("effective_beats") or []
            notes = str(data.get("adaptation_notes") or "")
            if not raw_beats:
                return default, notes
            return [
                EffectiveBeat(
                    order=int(eb.get("order", i + 1)),
                    phrase_anchor=str(eb.get("phrase_anchor", "")),
                    visual_type=str(eb.get("visual_type", "documentary_photo")),
                    on_screen_text=str(eb.get("on_screen_text", "")),
                    adaptation=eb.get("adaptation", "unchanged"),
                    source_beat_orders=list(eb.get("source_beat_orders") or [eb.get("order", i + 1)]),
                    transition_hint=str(eb.get("transition_hint") or ""),
                    motion_hint=str(eb.get("motion_hint") or ""),
                )
                for i, eb in enumerate(raw_beats)
            ], notes
        except Exception as exc:
            logger.warning("LLM montage planner segment %d fallback : %s", order, exc)
            return default, ""

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        return parse_json_text(raw, "montage_planner_agent")


async def load_latest_montage_plan(project_id: uuid.UUID) -> MontagePlanData | None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MontagePlan)
            .where(MontagePlan.project_id == project_id)
            .order_by(MontagePlan.iteration.desc(), MontagePlan.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if not row or not row.plan_data:
            return None
        return MontagePlanData.from_db_dict(row.plan_data)
