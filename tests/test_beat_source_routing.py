from __future__ import annotations

from agent.core.visual_beats import VisualBeat
from agent.skills.media.beat_source_routing import (
    merge_sources,
    resolve_beat_sources,
)


def _beat(visual_type: str) -> VisualBeat:
    return VisualBeat(
        order=1,
        phrase_anchor="test anchor phrase",
        visual_type=visual_type,
        prompt="test prompt",
    )


def test_sports_action_prioritizes_pexels() -> None:
    plan = resolve_beat_sources(
        _beat("sports_action"),
        {"order": 1, "source_hint": ["gallica"]},
        ["gallica", "europeana", "wikimedia"],
    )
    assert not plan.skip_stock
    assert plan.sources[0] == "pexels"
    assert "mapped:visual_type:sports_action" == plan.routing_reason


def test_space_photo_prioritizes_nasa() -> None:
    plan = resolve_beat_sources(
        _beat("space_photo"),
        {"order": 1},
        ["wikimedia", "pexels"],
    )
    assert plan.sources[0] == "nasa"


def test_scientific_diagram_skips_stock() -> None:
    plan = resolve_beat_sources(
        _beat("scientific_diagram"),
        {"order": 1},
        ["pexels", "wikimedia"],
    )
    assert plan.skip_stock
    assert plan.sources == []
    assert plan.routing_reason.startswith("ai_only:")


def test_documentary_photo_falls_back_to_segment_hint() -> None:
    plan = resolve_beat_sources(
        _beat("documentary_photo"),
        {"order": 1, "source_hint": ["gallica", "wikimedia"]},
        ["pexels", "unsplash"],
    )
    assert not plan.skip_stock
    assert plan.sources[0] == "gallica"
    assert "fallback" in plan.routing_reason


def test_merge_sources_deduplicates() -> None:
    merged = merge_sources(["pexels", "wikimedia"], ["wikimedia", "unsplash"])
    assert merged == ["pexels", "wikimedia", "unsplash"]
