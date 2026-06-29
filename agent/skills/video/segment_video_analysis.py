from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from agent.agents.video_analyst_agent import (
    VideoAnalysis,
    analyze_video_with_gemini,
)
from agent.core.concurrency import bounded_gather
from agent.core.database import AsyncSessionFactory, AudioFile, CriticReport, Video
from agent.core.llm_usage import LlmUsageRecord, merge_usage_records
from agent.core.project_cost import persist_standalone_agent_run
from agent.skills.video.ffmpeg_runtime import run_ffmpeg

logger = logging.getLogger(__name__)

SEGMENT_ANALYST_PROMPT = """Analyse ce segment (partie {segment_order}) d'une vidéo éducative.

Chaîne : {channel_name} | Thème : {theme}
Segment : {start_s:.0f}s → {end_s:.0f}s | Itération : {iteration}

Concentre-toi sur les problèmes visuels et techniques **de ce segment uniquement**.
Les timestamp_s dans issues doivent être relatifs au début de ce segment (0 = début du clip).

Retourne UNIQUEMENT le JSON structuré demandé (sans markdown)."""


async def segment_time_ranges(
    project_id: uuid.UUID,
    iteration: int,
) -> dict[int, tuple[float, float]]:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(AudioFile)
            .where(AudioFile.project_id == project_id, AudioFile.iteration == iteration)
            .order_by(AudioFile.segment_order)
        )
        audio_files = list(result.scalars().all())

    ranges: dict[int, tuple[float, float]] = {}
    offset = 0.0
    for af in audio_files:
        order = int(af.segment_order or 0)
        duration = float(af.duration_s or 0.0)
        if order <= 0 or duration <= 0:
            continue
        ranges[order] = (offset, offset + duration)
        offset += duration
    return ranges


async def extract_segment_clip(
    full_video: Path,
    start_s: float,
    end_s: float,
    out_path: Path,
) -> None:
    duration = max(end_s - start_s, 0.5)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-i", str(full_video),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        str(out_path),
    ]
    await run_ffmpeg(cmd)


async def load_previous_video_analysis(
    project_id: uuid.UUID,
    iteration: int,
) -> VideoAnalysis | None:
    async with AsyncSessionFactory() as session:
        report_result = await session.execute(
            select(CriticReport)
            .join(Video, Video.id == CriticReport.video_id)
            .where(
                Video.project_id == project_id,
                CriticReport.iteration == iteration,
            )
            .order_by(CriticReport.created_at.desc())
            .limit(1)
        )
        report = report_result.scalar_one_or_none()
    if report is None:
        return None
    va = report.video_analysis or {}
    status = va.get("analysis_status")
    if status is not None and status != "ok":
        return None
    if not va:
        return None
    return _analysis_from_dict(va)


def _analysis_from_dict(data: dict) -> VideoAnalysis:
    return VideoAnalysis(
        score=int(data.get("score", 0)),
        issues=list(data.get("issues") or []),
        visual_coherence=int(data.get("visual_coherence", 0)),
        subtitle_quality=int(data.get("subtitle_quality", 0)),
        rhythm=int(data.get("rhythm", 0)),
        voice_expressiveness=int(data.get("voice_expressiveness", 0)),
        summary=str(data.get("summary", "")),
        raw=data,
    )


def merge_video_analyses(
    previous: VideoAnalysis,
    partials: dict[int, VideoAnalysis],
    segment_durations: dict[int, float],
    segment_offsets: dict[int, float],
) -> VideoAnalysis:
    kept_issues = []
    for issue in previous.issues:
        ts = int(issue.get("timestamp_s", 0))
        kept = True
        for order, analysis in partials.items():
            start = segment_offsets.get(order, 0.0)
            end = start + segment_durations.get(order, 0.0)
            if start <= ts < end:
                kept = False
                break
        if kept:
            kept_issues.append(issue)

    merged_issues = list(kept_issues)
    for order, analysis in sorted(partials.items()):
        offset = int(segment_offsets.get(order, 0.0))
        for issue in analysis.issues:
            item = dict(issue)
            item["timestamp_s"] = int(item.get("timestamp_s", 0)) + offset
            merged_issues.append(item)

    total_duration = sum(segment_durations.values()) or 1.0
    weighted_score = previous.score * max(total_duration - sum(
        segment_durations.get(o, 0.0) for o in partials
    ), 0.0)
    for order, analysis in partials.items():
        weighted_score += analysis.score * segment_durations.get(order, 0.0)
    global_score = int(round(weighted_score / total_duration))

    def _blend(prev_val: int, max_val: int, field: str) -> int:
        acc = 0.0
        for order, analysis in partials.items():
            val = getattr(analysis, field, 0)
            acc += val * segment_durations.get(order, 0.0)
        unchanged_dur = max(total_duration - sum(
            segment_durations.get(o, 0.0) for o in partials
        ), 0.0)
        acc += getattr(previous, field, 0) * unchanged_dur
        return int(round(acc / total_duration))

    summaries = [previous.summary] + [a.summary for a in partials.values() if a.summary]
    return VideoAnalysis(
        score=global_score,
        issues=merged_issues,
        visual_coherence=_blend(previous.visual_coherence, 25, "visual_coherence"),
        subtitle_quality=_blend(previous.subtitle_quality, 25, "subtitle_quality"),
        rhythm=_blend(previous.rhythm, 25, "rhythm"),
        voice_expressiveness=_blend(previous.voice_expressiveness, 10, "voice_expressiveness"),
        summary=" ".join(s for s in summaries if s)[:500],
        raw={"partial_segments": list(partials.keys())},
    )


async def _analyze_one_segment(
    *,
    full_video: Path,
    tmp_dir: Path,
    segment_order: int,
    start_s: float,
    end_s: float,
    channel_name: str,
    theme: str,
    iteration: int,
    api_key: str,
) -> tuple[int, VideoAnalysis, LlmUsageRecord]:
    clip_path = tmp_dir / f"segment_{segment_order:02d}.mp4"
    await extract_segment_clip(full_video, start_s, end_s, clip_path)
    prompt = SEGMENT_ANALYST_PROMPT.format(
        segment_order=segment_order,
        channel_name=channel_name,
        theme=theme,
        start_s=start_s,
        end_s=end_s,
        iteration=iteration,
    )
    analysis, usage = await analyze_video_with_gemini(
        clip_path,
        channel_name,
        theme,
        end_s - start_s,
        iteration,
        api_key,
        prompt_override=prompt,
    )
    return segment_order, analysis, usage


async def run_partial_video_analysis(
    *,
    project_id: uuid.UUID,
    video_path: Path | str,
    changed_orders: set[int],
    channel_name: str,
    theme: str,
    duration_s: float,
    iteration: int,
    api_key: str,
) -> VideoAnalysis | None:
    path = Path(video_path)
    if not path.exists() or not changed_orders:
        return None

    previous = await load_previous_video_analysis(project_id, iteration - 1)
    if previous is None:
        return None

    ranges = await segment_time_ranges(project_id, iteration)
    if not ranges:
        return None

    tmp_dir = path.parent / f"_analysis_iter{iteration}"
    tasks = []
    for order in sorted(changed_orders):
        if order not in ranges:
            continue
        start_s, end_s = ranges[order]
        tasks.append(
            _analyze_one_segment(
                full_video=path,
                tmp_dir=tmp_dir,
                segment_order=order,
                start_s=start_s,
                end_s=end_s,
                channel_name=channel_name,
                theme=theme,
                iteration=iteration,
                api_key=api_key,
            )
        )

    if not tasks:
        return previous

    results = await bounded_gather(*tasks)
    partials: dict[int, VideoAnalysis] = {}
    usages: list[LlmUsageRecord] = []
    segment_durations = {o: ranges[o][1] - ranges[o][0] for o in ranges}
    segment_offsets = {o: ranges[o][0] for o in ranges}

    for order, analysis, usage in results:
        partials[order] = analysis
        usages.append(usage)

    merged = merge_video_analyses(
        previous,
        partials,
        segment_durations,
        segment_offsets,
    )

    if usages:
        total_usage = merge_usage_records(usages)
        await persist_standalone_agent_run(
            project_id,
            "video_analyst_agent",
            iteration,
            total_usage,
            output_json={
                "partial": True,
                "changed_segments": sorted(changed_orders),
                "score": merged.score,
            },
        )

    logger.info(
        "Analyse segmentaire itération %d : %d segment(s) ré-analysé(s)",
        iteration,
        len(partials),
    )
    return merged
