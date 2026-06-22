from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from agent.agents.critic_agent import CriticAgent
from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.database import Video


def test_critic_short_duration_override_forces_iterate() -> None:
    ctx = MagicMock()
    ctx.target_duration_seconds = 60
    ctx.channel_config = ChannelRuntimeConfig(max_short_duration_s=120)

    video = Video(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        video_type="short_master",
        duration_s=150.0,
    )
    data: dict = {"requested_changes": [], "feedback": {}}

    decision, start_from = CriticAgent._apply_short_duration_override(
        ctx,
        video,
        is_short=True,
        decision="approve",
        start_from_value="editor_agent",
        data=data,
    )

    assert decision == "iterate"
    assert start_from == "revision_agent"
    assert data["requested_changes"]
