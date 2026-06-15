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
    llm_response = json.dumps({"segments": adapted_segments, "total_duration_s": 20})

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=llm_response)]

    with (
        patch("agent.skills.media.scenario_media_gap.settings") as mock_settings,
        patch("agent.skills.media.scenario_media_gap.anthropic.AsyncAnthropic") as mock_client_cls,
        patch("agent.skills.media.scenario_media_gap.AsyncSessionFactory") as mock_session_factory,
    ):
        mock_settings.anthropic_api_key = "test-key"
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)
        mock_client_cls.return_value = mock_client

        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session
        mock_session.get = AsyncMock(return_value=scenario)

        result, adapted_orders = await adapt_scenario_for_media_gaps(
            scenario,
            gaps,
            theme="Nature",
        )

    assert adapted_orders == [1]
    assert result.segments[0]["visual_optional"] is True
