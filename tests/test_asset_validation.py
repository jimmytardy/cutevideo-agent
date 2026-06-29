"""Tests asset_validation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.skills.media.asset_validation import audit_selected_media, validate_single_asset
from agent.skills.media.run_session import MediaRunSession


@pytest.mark.asyncio
async def test_audit_selected_media_keeps_forced_best_above_floor() -> None:
    session = MediaRunSession()
    ctx = MagicMock_channel()
    selected = [{
        "_relevance_forced_fallback": True,
        "_relevance_score": 60,
        "asset_type": "image",
        "url": "http://a.jpg",
    }]
    result = await audit_selected_media(
        session,
        selected,
        ctx=ctx,
        segment={"order": 1, "title": "T"},
        min_relevance=75,
        output_dir=SimpleNamespace(__truediv__=lambda s, o: s),
        validation_brief=SimpleNamespace(min_score_for_segment=lambda o: 75),
        assets_needed=1,
        video_target=0,
    )
    assert len(result) == 1


@pytest.mark.asyncio
async def test_audit_selected_media_drops_forced_best_below_floor() -> None:
    session = MediaRunSession()
    ctx = MagicMock_channel()
    selected = [{
        "_relevance_forced_fallback": True,
        "_relevance_score": 40,
        "asset_type": "image",
        "url": "http://a.jpg",
    }]
    result = await audit_selected_media(
        session,
        selected,
        ctx=ctx,
        segment={"order": 1, "title": "T"},
        min_relevance=75,
        output_dir=SimpleNamespace(__truediv__=lambda s, o: s),
        validation_brief=SimpleNamespace(min_score_for_segment=lambda o: 75),
        assets_needed=1,
        video_target=0,
    )
    assert len(result) == 0


@pytest.mark.asyncio
async def test_validate_single_asset_delegates_to_filter() -> None:
    session = MediaRunSession()
    ctx = MagicMock_channel()
    item = {"url": "http://img.jpg", "asset_type": "image"}
    with patch(
        "agent.skills.media.asset_validation.filter_candidates_by_relevance",
        new=AsyncMock(return_value=([{**item, "_relevance_validated": True}], [])),
    ):
        validated = await validate_single_asset(
            session,
            item,
            ctx=ctx,
            segment={"order": 1},
            min_relevance=70,
            output_dir=SimpleNamespace(__truediv__=lambda s, o: s),
            validation_brief=SimpleNamespace(),
        )
    assert validated is not None


def MagicMock_channel() -> SimpleNamespace:
    return SimpleNamespace(
        theme="Sujet",
        theme_category="nature",
        channel_config=SimpleNamespace(
            media_sources=SimpleNamespace(forced_best_min_score=50),
        ),
    )
