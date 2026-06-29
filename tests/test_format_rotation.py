from __future__ import annotations

from agent.core.content_plan_models import VideoTopicPlan
from agent.core.editorial_formats import DEFAULT_EDITORIAL_FORMATS
from agent.skills.content_planning.format_rotation import (
    apply_format_rotation_to_plan,
    assign_formats_to_long_topics,
    pick_available_format_ids,
    pick_intro_outro_variants,
)


def test_pick_available_format_ids_excludes_recent() -> None:
    bank = DEFAULT_EDITORIAL_FORMATS[:4]
    recent = ["enquete", "liste-classement", "mythe-vs-realite"]
    available = pick_available_format_ids(bank, recent, k=3)
    assert "enquete" not in available
    assert "liste-classement" not in available
    assert "mythe-vs-realite" not in available
    assert available


def test_pick_available_format_ids_fallback_when_bank_small() -> None:
    bank = DEFAULT_EDITORIAL_FORMATS[:2]
    recent = ["enquete", "liste-classement", "enquete"]
    available = pick_available_format_ids(bank, recent, k=3)
    assert available == ["liste-classement"] or available == ["enquete"]


def test_assign_formats_no_repeat_on_window() -> None:
    bank = DEFAULT_EDITORIAL_FORMATS[:6]
    topics = [
        VideoTopicPlan(
            priority=1,
            format="long",
            provisional_title="T1",
            angle="A1",
            narrative_format="",
            estimated_duration_s=1800,
            sub_theme="histoire",
            subject="Sujet 1",
        ),
        VideoTopicPlan(
            priority=2,
            format="long",
            provisional_title="T2",
            angle="A2",
            narrative_format="",
            estimated_duration_s=1800,
            sub_theme="histoire",
            subject="Sujet 2",
        ),
    ]
    history = ["enquete", "liste-classement", "mythe-vs-realite"]
    assigned = assign_formats_to_long_topics(topics, bank, history, [], [], k=3)
    ids = [t.editorial_format_id for t in assigned]
    assert ids[0] != ids[1]
    assert ids[0] not in history[:3]
    assert all(t.intro_variant for t in assigned)


def test_pick_intro_outro_variants_rotates() -> None:
    fmt = DEFAULT_EDITORIAL_FORMATS[0]
    intro1, outro1 = pick_intro_outro_variants(fmt, [], [])
    intro2, _ = pick_intro_outro_variants(fmt, [intro1], [])
    assert intro1
    assert intro2 != intro1 or len(fmt.intro_variants) == 1


def test_apply_format_rotation_short_inherits_parent() -> None:
    from agent.core.content_plan_models import DailyContentPlan, ThemeAnalysis

    bank = DEFAULT_EDITORIAL_FORMATS[:3]
    plan = DailyContentPlan(
        plan_date="2026-06-30",
        channel_slug="test",
        theme_category="histoire",
        long_count=1,
        short_count=1,
        theme_analysis=ThemeAnalysis(),
        long_videos=[
            VideoTopicPlan(
                priority=1,
                format="long",
                provisional_title="Long",
                angle="Angle",
                narrative_format="",
                estimated_duration_s=1800,
                sub_theme="histoire",
                subject="Sujet long",
            )
        ],
        short_videos=[
            VideoTopicPlan(
                priority=1,
                format="short_derived",
                provisional_title="Short",
                angle="Angle short",
                narrative_format="",
                estimated_duration_s=90,
                sub_theme="histoire",
                subject="Sujet short",
                parent_long_index=0,
            )
        ],
    )
    rotated = apply_format_rotation_to_plan(plan, bank, [], [], [], k=2)
    assert rotated.long_videos[0].editorial_format_id
    assert rotated.short_videos[0].editorial_format_id == rotated.long_videos[0].editorial_format_id
