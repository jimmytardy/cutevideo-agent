from __future__ import annotations

from agent.core.montage_plan import BeatClipPlan, MontagePlanData, SegmentMontagePlan
from agent.core.pipeline_restart import (
    critic_rework_iteration,
    needs_revision_agent,
    resolve_restart_step,
    should_skip_pool_reuse,
)
from agent.skills.video.trim_selector import select_trim_window


def test_resolve_restart_step_media_over_editor() -> None:
    changes = [{"agent": "editor_agent", "change_description": "timing"}, {"agent": "media_agent", "change_description": "images"}]
    assert resolve_restart_step(changes, "editor_agent") == "media_agent"


def test_needs_revision_when_media_in_changes() -> None:
    changes = [{"agent": "media_agent", "change_description": "varier visuels"}]
    assert needs_revision_agent(changes, "editor_agent") is True


def test_skip_pool_reuse_on_static_feedback() -> None:
    changes = [{"agent": "media_agent", "change_description": "plans statiques trop longs"}]
    assert should_skip_pool_reuse(changes) is True


def test_critic_rework_iteration_after_rejection() -> None:
    assert critic_rework_iteration(1) == 2
    assert critic_rework_iteration(2) == 3
    assert critic_rework_iteration(None) == 2


def test_trim_selector_uses_best_segment() -> None:
    from agent.core.montage_plan import ClipMetadata, ClipSegmentMeta

    meta = ClipMetadata(
        motion_score=80,
        best_segments=[ClipSegmentMeta(start_s=2.0, end_s=8.0, reason="action")],
    )
    sel = select_trim_window(
        source_duration_s=30.0,
        target_duration_s=6.0,
        phrase_anchor="test",
        visual_type="documentary_photo",
        clip_metadata=meta,
    )
    assert sel.start_s == 2.0
    assert sel.end_s <= 8.0


def test_montage_plan_roundtrip() -> None:
    import uuid

    plan = MontagePlanData(
        project_id=uuid.uuid4(),
        iteration=1,
        segments=[
            SegmentMontagePlan(
                segment_order=1,
                clips=[
                    BeatClipPlan(
                        beat_order=1,
                        asset_path="/tmp/a.jpg",
                        asset_type="image",
                        timeline_start_s=0.0,
                        timeline_end_s=5.0,
                    )
                ],
            )
        ],
    )
    restored = MontagePlanData.from_db_dict(plan.to_db_dict())
    assert len(restored.segments[0].clips) == 1
