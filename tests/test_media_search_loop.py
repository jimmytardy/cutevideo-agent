"""Tests boucle de recherche media_agent."""

from __future__ import annotations

from agent.skills.media.asset_resolver import dedupe_and_filter, select_assets
from agent.core.media_validation import MediaValidationBrief


def test_dedupe_and_filter_excludes_rejected_urls() -> None:
    candidates = [
        {"url": "http://a.jpg", "asset_type": "image"},
        {"url": "http://b.jpg", "asset_type": "image"},
        {"url": "http://c.jpg", "asset_type": "image"},
    ]
    filtered = dedupe_and_filter(
        candidates, 0, exclude_urls={"http://b.jpg"}
    )
    assert len(filtered) == 2
    assert all(c["url"] != "http://b.jpg" for c in filtered)


def test_select_assets_prioritizes_video() -> None:
    candidates = [
        {"asset_type": "image", "url": "img1"},
        {"asset_type": "video", "url": "vid1"},
        {"asset_type": "image", "url": "img2"},
    ]
    selected = select_assets(candidates, video_target=1, total_needed=2)
    assert selected[0]["asset_type"] == "video"
    assert len(selected) == 2


def test_validation_brief_min_score_for_segment() -> None:
    from agent.core.media_validation import SegmentValidationBrief

    brief = MediaValidationBrief(
        min_relevance_score=75,
        segments={1: SegmentValidationBrief(min_relevance_score=85)},
    )
    assert brief.min_score_for_segment(1) == 85
    assert brief.min_score_for_segment(2) == 75
