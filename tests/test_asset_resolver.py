"""Tests asset_resolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.skills.media.asset_resolver import (
    build_anchored_queries,
    dedupe_and_filter,
    search_with_fallback,
    select_assets,
)


def test_dedupe_and_filter_excludes_rejected_urls() -> None:
    candidates = [
        {"url": "http://a.jpg", "asset_type": "image"},
        {"url": "http://b.jpg", "asset_type": "image"},
        {"url": "http://c.jpg", "asset_type": "image"},
    ]
    filtered = dedupe_and_filter(candidates, 0, exclude_urls={"http://b.jpg"})
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


def test_build_anchored_queries_includes_video_subject() -> None:
    queries = build_anchored_queries(
        ["rouge-gorge", "European robin"],
        "Le rouge-gorge familier",
        "Habitat",
    )
    assert any("Le rouge-gorge familier" in q for q in queries)
    assert queries[0] == ["rouge-gorge", "European robin"]


def test_build_anchored_queries_fallback_to_subject_only() -> None:
    queries = build_anchored_queries([], "Napoléon à Waterloo", "La bataille")
    assert queries == [["Napoléon à Waterloo"]]


@pytest.mark.asyncio
async def test_search_with_fallback_primary_source() -> None:
    from agent.skills.media.run_session import MediaRunSession

    session = MediaRunSession()
    with patch(
        "agent.skills.media.asset_resolver.search_source",
        new=AsyncMock(return_value=[{"url": "http://x.jpg", "asset_type": "image"}]),
    ):
        found = await search_with_fallback(
            session,
            ["wikimedia"],
            ["bird"],
            "",
            {"title": "Test"},
            min_candidates=1,
            video_subject="Birds",
        )
    assert len(found) == 1
