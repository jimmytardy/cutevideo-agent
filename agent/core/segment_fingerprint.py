from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select

from agent.core.database import AsyncSessionFactory, MediaAsset, MontagePlan, Scenario
from agent.core.montage_plan import MontagePlanData


def _hash_payload(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def segment_scenario_fingerprint(segment: dict) -> str:
    beats = segment.get("visual_beats") or segment.get("beats") or []
    return _hash_payload({
        "narration": segment.get("narration") or segment.get("text") or "",
        "beats": beats,
        "on_screen_text": segment.get("on_screen_text"),
    })


def segment_media_fingerprint(assets: list[MediaAsset]) -> str:
    rows = sorted(
        [
            {
                "id": str(a.id),
                "source": a.source,
                "local_path": a.local_path,
                "selected": a.selected,
                "beat_index": a.beat_index,
            }
            for a in assets
            if a.selected
        ],
        key=lambda r: (r.get("beat_index") or 0, r["id"]),
    )
    return _hash_payload(rows)


def segment_montage_fingerprint(plan: MontagePlanData, segment_order: int) -> str:
    seg = next((s for s in plan.segments if s.segment_order == segment_order), None)
    if seg is None:
        return ""
    clips = [
        {
            "asset_path": c.asset_path,
            "timeline_start_s": c.timeline_start_s,
            "timeline_end_s": c.timeline_end_s,
            "trim_start": c.source_trim_start_s,
            "trim_end": c.source_trim_end_s,
            "motion": c.motion_style,
        }
        for c in seg.clips
    ]
    return _hash_payload(clips)


async def compute_segment_fingerprints(
    project_id: uuid.UUID,
    iteration: int,
) -> dict[int, str]:
    async with AsyncSessionFactory() as session:
        scenario_result = await session.execute(
            select(Scenario)
            .where(Scenario.project_id == project_id, Scenario.iteration == iteration)
            .order_by(Scenario.created_at.desc())
            .limit(1)
        )
        scenario = scenario_result.scalar_one_or_none()
        if scenario is None:
            scenario_result = await session.execute(
                select(Scenario)
                .where(Scenario.project_id == project_id)
                .order_by(Scenario.created_at.desc())
                .limit(1)
            )
            scenario = scenario_result.scalar_one_or_none()

        plan_result = await session.execute(
            select(MontagePlan)
            .where(MontagePlan.project_id == project_id, MontagePlan.iteration == iteration)
            .order_by(MontagePlan.created_at.desc())
            .limit(1)
        )
        plan_row = plan_result.scalar_one_or_none()
        plan_data = (
            MontagePlanData.from_db_dict(plan_row.plan_data)
            if plan_row and plan_row.plan_data
            else None
        )

        media_result = await session.execute(
            select(MediaAsset).where(
                MediaAsset.project_id == project_id,
                MediaAsset.iteration == iteration,
            )
        )
        media_assets = list(media_result.scalars().all())

    segments = (scenario.segments or []) if scenario else []
    fingerprints: dict[int, str] = {}
    for idx, seg in enumerate(segments):
        order = int(seg.get("order", idx + 1))
        seg_media = [a for a in media_assets if a.segment_order == order]
        parts = [
            segment_scenario_fingerprint(seg),
            segment_media_fingerprint(seg_media),
        ]
        if plan_data is not None:
            parts.append(segment_montage_fingerprint(plan_data, order))
        fingerprints[order] = _hash_payload(parts)
    return fingerprints


async def compute_changed_segments(
    project_id: uuid.UUID,
    iteration: int,
) -> set[int] | None:
    """Segments modifiés vs itération précédente. None = fallback analyse complète."""
    if iteration <= 1:
        return None
    current = await compute_segment_fingerprints(project_id, iteration)
    previous = await compute_segment_fingerprints(project_id, iteration - 1)
    if not current:
        return None
    if not previous:
        return set(current.keys())
    all_orders = set(current.keys()) | set(previous.keys())
    changed = {
        order
        for order in all_orders
        if current.get(order) != previous.get(order)
    }
    return changed
