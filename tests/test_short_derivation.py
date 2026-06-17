"""Tests short derivation config et helpers."""

from __future__ import annotations

import uuid
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from agent.core.channel_config import ShortDerivationConfig, resolve_channel_config
from agent.core.database import Channel
from agent.core.orchestrator import Orchestrator, PipelineContext
from agent.core.short_derivation import (
    DerivedShortPlan,
    derivation_iteration,
    native_video_type,
)


def test_short_derivation_config_defaults() -> None:
    cfg = ShortDerivationConfig()
    assert cfg.strategy == "hybrid"
    assert cfg.mode == "free_sources_only"
    assert cfg.hybrid_teaser_max_clips == 2


def test_resolve_channel_config_short_derivation() -> None:
    channel = Channel(
        id=uuid.uuid4(),
        slug="test",
        name="Test",
        theme_category="science",
        config={"production": {"short_derivation_strategy": "native"}},
    )
    cfg = resolve_channel_config(channel)
    assert cfg.short_derivation.strategy == "native"


def test_derivation_iteration_and_video_type() -> None:
    assert derivation_iteration(0) == 10_000
    assert derivation_iteration(2) == 10_002
    assert native_video_type(1) == "short_native_01"


@pytest.mark.asyncio
async def test_mixed_hybrid_runs_native_and_crop_pipelines() -> None:
    orch = Orchestrator()
    ctx = MagicMock(spec=PipelineContext)
    ctx.project_id = uuid.uuid4()

    session = AsyncMock()
    with patch.object(orch, "_run_creation_pipeline", new_callable=AsyncMock) as mock_create, patch.object(
        orch, "_run_native_shorts_pipeline", new_callable=AsyncMock
    ) as mock_native, patch.object(
        orch, "_run_shorts_pipeline", new_callable=AsyncMock
    ) as mock_crop, patch.object(
        orch, "_run_metadata", new_callable=AsyncMock
    ), patch.object(
        orch, "_run_thumbnail", new_callable=AsyncMock
    ), patch(
        "agent.core.storage.cleanup_local_videos_for_project", new_callable=AsyncMock
    ), patch(
        "agent.core.storage.cleanup_temp_ai_images", new_callable=AsyncMock
    ), patch(
        "agent.core.storage.cleanup_temp_ai_images", new_callable=AsyncMock
    ), patch.object(
        orch, "_update_project_status", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator._raise_if_cancelled", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.resolve_user_limits", new_callable=AsyncMock, return_value=None
    ), patch(
        "agent.core.orchestrator.can_start_pipeline", new_callable=AsyncMock, return_value=True
    ), patch(
        "agent.core.orchestrator.load_channel_context", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.AsyncSessionFactory"
    ) as mock_session_factory:
        mock_session_factory.return_value.__aenter__.return_value = session

        project = MagicMock()
        project.id = ctx.project_id
        project.channel_id = uuid.uuid4()
        project.theme = "Test"
        project.target_duration_seconds = 1800
        project.config = {"format": "long"}
        project.status = "pending"

        channel = MagicMock()
        channel.id = project.channel_id
        channel.slug = "test"
        channel.theme_category = "science"
        channel.niche_prompt = ""
        channel.name = "Test Channel"
        channel.max_concurrent_pipelines = 1

        orch._get_project = AsyncMock(return_value=project)
        orch._get_channel = AsyncMock(return_value=channel)

        from agent.core.channel_config import ChannelRuntimeConfig, ShortDerivationConfig

        channel_config = ChannelRuntimeConfig(
            production_mode="mixed",
            short_derivation=ShortDerivationConfig(strategy="hybrid"),
        )
        with patch(
            "agent.core.orchestrator.resolve_channel_config", return_value=channel_config
        ):
            await orch.run_pipeline(ctx.project_id)

    mock_create.assert_awaited_once()
    mock_native.assert_awaited_once()
    mock_native.assert_awaited_with(ANY, planned_only=True)
    mock_crop.assert_awaited_once()
    mock_crop.assert_awaited_with(ANY, teaser_only=True)


def test_clipper_max_clips_slicing() -> None:
    from agent.agents.clipper_agent import ClipCandidate

    clips = [
        ClipCandidate(
            title=f"Clip {i}",
            hook="Hook",
            segment_start_order=1,
            segment_end_order=1,
            estimated_start_s=0,
            estimated_end_s=60,
            duration_s=60,
            shortability_score=90 - i,
            reason="test",
            cta="CTA",
        )
        for i in range(5)
    ]
    max_clips_limit = 2
    result = clips[: max(max_clips_limit, 1)]
    assert len(result) == 2
    assert result[0].shortability_score == 90


def test_derived_short_plan_to_scenario_dict() -> None:
    plan = DerivedShortPlan(
        index=0,
        title="Titre",
        hook="Hook",
        cta="CTA",
        segments=[{"order": 1}],
        total_duration_s=90,
    )
    data = plan.to_scenario_dict()
    assert data["title"] == "Titre"
    assert len(data["segments"]) == 1
