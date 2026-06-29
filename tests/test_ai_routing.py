"""Tests ai/routing budget et apply result."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.skills.media.ai_image_result import AiImageResult
from agent.skills.media.run_session import MediaRunSession
from agent.skills.media_sources.ai.routing import (
    apply_ai_image_result,
    can_generate_ai_image,
    effective_max_ai_images,
)


def test_effective_max_ai_images_niche_high() -> None:
    session = MediaRunSession()
    session.validation_brief = SimpleNamespace(niche_risk="high")
    ai_cfg = SimpleNamespace(max_ai_images_per_video=5)
    assert effective_max_ai_images(session, ai_cfg) == 15


def test_effective_max_ai_images_default() -> None:
    session = MediaRunSession()
    session.validation_brief = SimpleNamespace(niche_risk="low")
    ai_cfg = SimpleNamespace(max_ai_images_per_video=5)
    assert effective_max_ai_images(session, ai_cfg) == 5


@pytest.mark.asyncio
async def test_can_generate_ai_image_respects_video_cap() -> None:
    session = MediaRunSession()
    session.ai_images_used = 10
    session.validation_brief = SimpleNamespace(niche_risk="low")
    ai_cfg = SimpleNamespace(
        plan=SimpleNamespace(value="flux_pro"),
        enabled=True,
        max_ai_images_per_video=10,
        max_ai_images_per_week=None,
    )
    ctx = MagicMock()
    assert await can_generate_ai_image(session, ctx, ai_cfg) is False


@pytest.mark.asyncio
async def test_apply_ai_image_result_api_failed_adds_gap() -> None:
    session = MediaRunSession()
    ctx = MagicMock()
    segment = {"order": 2}
    selected: list[dict] = []
    await apply_ai_image_result(
        session,
        AiImageResult(outcome="api_failed"),
        ctx=ctx,
        segment=segment,
        ai_prompt="prompt",
        selected=selected,
        dev_attempts=2,
        paid_attempts=3,
    )
    assert len(session.media_gaps) == 1
    assert session.media_gaps[0].segment_order == 2
    assert 2 in session.segment_media_gaps


@pytest.mark.asyncio
async def test_apply_ai_image_result_license_rejected() -> None:
    session = MediaRunSession()
    ctx = MagicMock()
    segment = {"order": 1}
    selected: list[dict] = []
    with patch(
        "agent.skills.media_sources.ai.routing.is_publishable",
        return_value=(False, "unknown_license"),
    ):
        await apply_ai_image_result(
            session,
            AiImageResult(outcome="validated", item={"source": "ai_image", "url": "x"}),
            ctx=ctx,
            segment=segment,
            ai_prompt="p",
            selected=selected,
            dev_attempts=1,
            paid_attempts=1,
        )
    assert len(session.media_gaps) == 1
    assert "ai_license_rejected" in session.media_gaps[0].reason
