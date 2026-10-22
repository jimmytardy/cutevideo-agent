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
    assert brief.words_per_second == 3.1


def test_build_brief_carries_channel_words_per_second() -> None:
    cfg = ChannelRuntimeConfig(words_per_second=2.7)
    assert build_brief(_ctx(channel_config=cfg)).words_per_second == 2.7


def test_build_brief_clamps_duration_and_iterations() -> None:
    brief = build_brief(_ctx(target_duration_seconds=1800, max_critic_iterations=20))
    assert brief.target_duration_s == 180
    assert brief.max_iterations == 6


def test_runner_refuses_to_start_without_owner_anthropic_key(tmp_path, monkeypatch) -> None:
    """Sans clé Anthropic du propriétaire : erreur claire, et la création précédente n'est pas effacée."""
    import asyncio
    from unittest.mock import AsyncMock

    import pytest

    from agent.core import api_keys, claude_studio
    from studio.launcher import ClaudeRunError

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-platform")
    monkeypatch.setattr(api_keys, "resolve_user_keys", AsyncMock(return_value=api_keys.UserKeys()))
    runner = claude_studio.ClaudeStudioRunner(_ctx())
    runner.run_dir = tmp_path / "run"
    runner.run_dir.mkdir()
    (runner.run_dir / "result.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ClaudeRunError, match="Compte → Clés API"):
        asyncio.run(runner.run())
    assert (runner.run_dir / "result.json").exists()


def test_build_brief_scenario_and_video_loop_defaults() -> None:
    brief = build_brief(_ctx(channel_config=ChannelRuntimeConfig(), max_critic_iterations=None))
    assert (brief.min_scenario_score, brief.max_scenario_iterations) == (90, 5)
    assert (brief.min_score, brief.max_iterations) == (80, 5)


def test_build_brief_scenario_loop_channel_override() -> None:
    cfg = ChannelRuntimeConfig(min_scenario_score=95, max_scenario_iterations=9)
    brief = build_brief(_ctx(channel_config=cfg))
    assert brief.min_scenario_score == 95
    assert brief.max_scenario_iterations == 6  # plafond du contrat


def test_build_brief_ai_models_follow_channel_plan() -> None:
    from agent.core.channel_config import AiFallbackConfig, AiImagePlan
    from studio.launcher import usable_ai_models

    on = ChannelRuntimeConfig(ai_fallback=AiFallbackConfig(plan=AiImagePlan.FLUX_2_DEV, max_ai_images_per_video=3))
    brief = build_brief(_ctx(channel_config=on))
    assert brief.max_ai_images == 3
    assert brief.ai_models[0] == "flux_2_dev"

    # Plan « off » resté `enabled` : aucune image IA, même avec une clé fal.
    off = ChannelRuntimeConfig(ai_fallback=AiFallbackConfig(plan=AiImagePlan.OFF, enabled=True))
    brief = build_brief(_ctx(channel_config=off))
    assert brief.max_ai_images == 0
    assert brief.ai_models == []
    assert usable_ai_models(brief, MagicMock(fal="k", gcp_credentials_json=None)) == []
