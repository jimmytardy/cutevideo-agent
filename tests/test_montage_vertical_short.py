from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.agents.montage_planner_agent import MontagePlannerAgent
from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.database import Scenario


@pytest.mark.asyncio
async def test_montage_plan_is_vertical_for_short_target() -> None:
    ctx = MagicMock()
    ctx.project_id = uuid.uuid4()
    ctx.iteration = 1
    ctx.is_short_project = True
    ctx.derivation_short_index = None
    ctx.channel_config = ChannelRuntimeConfig(production_mode="mixed")

    scenario = Scenario(
        project_id=ctx.project_id,
        segments=[
            {
                "order": 1,
                "duration_s": 30,
                "mood": "calme",
                "visual_beats": [
                    {
                        "order": 1,
                        "visual_type": "documentary_photo",
                        "duration_hint_s": 30,
                        "phrase_anchor": "test",
                    }
                ],
            }
        ],
        total_duration_s=30,
        iteration=1,
    )

    with patch.object(
        MontagePlannerAgent,
        "_load_assets",
        new_callable=AsyncMock,
        return_value=([], []),
    ):
        plan = await MontagePlannerAgent.build_montage_plan_data(ctx, scenario, [], [])

    assert plan.is_vertical is True
