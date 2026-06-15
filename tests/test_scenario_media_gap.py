"""Tests adaptation scénario après gap média."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.database import Scenario
from agent.skills.media.ai_image_result import MediaGap
from agent.skills.media.scenario_media_gap import adapt_scenario_for_media_gaps


@pytest.mark.asyncio
async def test_adapt_scenario_for_media_gaps_sets_visual_optional() -> None:
    scenario = Scenario(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        segments=[
            {
                "order": 1,
                "title": "Intro",
                "narration_text": "Regardez cette scène précise.",
                "on_screen_text": "",
                "duration_s": 20,
            },
            {
                "order": 2,
                "title": "Suite",
                "narration_text": "Segment intact.",
                "on_screen_text": "Suite",
                "duration_s": 25,
            },
        ],
        total_duration_s=45,
        iteration=1,
    )
    gaps = [
        MediaGap(
            segment_order=1,
            reason="ai_generation_failed",
            attempts=6,
            prompt="forêt mystérieuse",
        )
    ]
    adapted_segments = [
        {
            "order": 1,
            "title": "Intro",
            "narration_text": "Écoutez cette explication sans visuel requis.",
            "on_screen_text": "Explication",
            "duration_s": 20,
            "visual_optional": True,
        }
    ]
    llm_response = json.dumps({"segments": adapted_segments, "total_duration_s": 45})

    with (
        patch("agent.core.llm_resolver.call_llm", new_callable=AsyncMock) as mock_llm,
        patch("agent.skills.media.scenario_media_gap.AsyncSessionFactory") as mock_session_factory,
    ):
        mock_llm.return_value = llm_response
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session
        mock_session.get = AsyncMock(return_value=scenario)

        result, adapted_orders = await adapt_scenario_for_media_gaps(
            scenario,
            gaps,
            theme="Nature",
            user_id=uuid.uuid4(),
        )

    assert adapted_orders == [1]
    assert result.segments[0]["visual_optional"] is True
    assert result.segments[0]["narration_text"].startswith("Écoutez")
    assert result.segments[1]["narration_text"] == "Segment intact."


@pytest.mark.asyncio
async def test_adapt_scenario_for_media_gaps_fallback_on_truncated_json() -> None:
    scenario = Scenario(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        segments=[
            {
                "order": 1,
                "title": "Intro",
                "narration_text": "Regardez cette scène précise.",
                "on_screen_text": "",
                "duration_s": 20,
            }
        ],
        total_duration_s=20,
        iteration=1,
    )
    gaps = [
        MediaGap(
            segment_order=1,
            reason="ai_generation_failed",
            attempts=6,
            prompt="forêt mystérieuse",
        )
    ]

    with (
        patch("agent.core.llm_resolver.call_llm", new_callable=AsyncMock) as mock_llm,
        patch("agent.skills.media.scenario_media_gap.AsyncSessionFactory") as mock_session_factory,
    ):
        mock_llm.return_value = '{"segments": [{"order": 1, "title": "Intro", "narration_text": "Texte tronqu'
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session
        mock_session.get = AsyncMock(return_value=scenario)

        result, adapted_orders = await adapt_scenario_for_media_gaps(
            scenario,
            gaps,
            theme="Nature",
            user_id=uuid.uuid4(),
        )

    assert adapted_orders == [1]
    assert result.segments[0]["visual_optional"] is True
    assert result.segments[0]["on_screen_text"] == "Intro"
