from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.claude_studio import build_brief
from agent.core.orchestrator import PipelineContext


def _ctx(**overrides) -> PipelineContext:
    base = dict(
        project_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        channel_slug="c",
        theme_category="science",
        niche_prompt="vulgarisation animale",
        channel_config=ChannelRuntimeConfig(min_critic_score=85, editorial_tone="drôle"),
        channel=MagicMock(creative_brief=None),
        theme="Les flamants roses",
        target_duration_seconds=45,
        max_critic_iterations=3,
        content_plan={"angle": "Ils naissent gris"},
    )
    base.update(overrides)
    return PipelineContext(**base)


def test_build_brief_maps_channel_and_project() -> None:
    brief = build_brief(_ctx())
    assert brief.theme == "Les flamants roses"
    assert brief.niche == "vulgarisation animale"
    assert brief.angle == "Ils naissent gris"
    assert brief.min_score == 85
    assert brief.max_iterations == 3
    assert brief.editorial_tone == "drôle"


def test_build_brief_clamps_duration_and_iterations() -> None:
    brief = build_brief(_ctx(target_duration_seconds=1800, max_critic_iterations=20))
    assert brief.target_duration_s == 180
    assert brief.max_iterations == 6
