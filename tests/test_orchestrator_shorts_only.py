"""Tests branchement orchestrateur mode shorts_only."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.orchestrator import Orchestrator, PipelineContext


@pytest.mark.asyncio
async def test_shorts_only_calls_platform_exports_not_clipper_pipeline() -> None:
    orch = Orchestrator()
    ctx = MagicMock(spec=PipelineContext)
    ctx.project_id = uuid.uuid4()

    with patch.object(orch, "_run_shorts_only_pipeline", new_callable=AsyncMock) as mock_shorts_only, patch.object(
        orch, "_run_platform_exports", new_callable=AsyncMock
    ) as mock_exports, patch.object(
        orch, "_run_shorts_pipeline", new_callable=AsyncMock
    ) as mock_clipper_pipeline, patch.object(
        orch, "_run_native_shorts_pipeline", new_callable=AsyncMock
    ) as mock_native, patch.object(
        orch, "_run_metadata", new_callable=AsyncMock
    ), patch.object(
        orch, "_run_thumbnail", new_callable=AsyncMock
    ), patch(
        "agent.core.storage.cleanup_local_videos_for_project", new_callable=AsyncMock
    ) as mock_cleanup, patch(
        "agent.core.storage.cleanup_temp_ai_images", new_callable=AsyncMock
    ), patch.object(
        orch, "_update_project_status", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator._raise_if_cancelled", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.resolve_user_limits", new_callable=AsyncMock,
    ) as mock_limits, patch(
        "agent.core.orchestrator.can_start_pipeline", new_callable=AsyncMock, return_value=True
    ), patch(
        "agent.core.orchestrator.load_channel_context", new_callable=AsyncMock
    ), patch(
        "agent.core.concurrency.AsyncSessionFactory"
    ) as mock_db_session_factory, patch(
        "agent.core.orchestrator.AsyncSessionFactory"
    ) as mock_session_factory:
        session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = session
        mock_db_session_factory.return_value.__aenter__.return_value = session
        limits = MagicMock()
        limits.unlimited_critic_iterations = False
        limits.max_critic_iterations = 5
        mock_limits.return_value = limits

        project = MagicMock()
        project.id = ctx.project_id
        project.channel_id = uuid.uuid4()
        project.theme = "Test"
        project.target_duration_seconds = 60
        project.config = {}
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

        from agent.core.channel_config import ChannelRuntimeConfig

        channel_config = ChannelRuntimeConfig(production_mode="shorts_only")
        with patch(
            "agent.core.orchestrator.resolve_channel_config", return_value=channel_config
        ):
            await orch.run_pipeline(ctx.project_id)

    mock_shorts_only.assert_awaited_once()
    mock_exports.assert_awaited_once()
    mock_clipper_pipeline.assert_not_awaited()
    mock_native.assert_not_awaited()
    mock_cleanup.assert_awaited_once_with(ctx.project_id)


@pytest.mark.asyncio
async def test_mixed_channel_short_target_uses_short_pipeline() -> None:
    orch = Orchestrator()
    project_id = uuid.uuid4()

    with patch.object(orch, "_run_shorts_only_pipeline", new_callable=AsyncMock) as mock_shorts_only, patch.object(
        orch, "_run_platform_exports", new_callable=AsyncMock
    ) as mock_exports, patch.object(
        orch, "_run_creation_pipeline", new_callable=AsyncMock
    ) as mock_creation, patch.object(
        orch, "_run_shorts_pipeline", new_callable=AsyncMock
    ) as mock_clipper_pipeline, patch.object(
        orch, "_run_metadata", new_callable=AsyncMock
    ), patch.object(
        orch, "_run_thumbnail", new_callable=AsyncMock
    ) as mock_thumbnail, patch(
        "agent.core.storage.cleanup_local_videos_for_project", new_callable=AsyncMock
    ), patch(
        "agent.core.storage.cleanup_temp_ai_images", new_callable=AsyncMock
    ), patch.object(
        orch, "_update_project_status", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator._raise_if_cancelled", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.resolve_user_limits", new_callable=AsyncMock,
    ) as mock_limits, patch(
        "agent.core.orchestrator.can_start_pipeline", new_callable=AsyncMock, return_value=True
    ), patch(
        "agent.core.orchestrator.load_channel_context", new_callable=AsyncMock
    ), patch(
        "agent.core.concurrency.AsyncSessionFactory"
    ), patch(
        "agent.core.orchestrator.AsyncSessionFactory"
    ) as mock_session_factory:
        session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = session
        limits = MagicMock()
        limits.unlimited_critic_iterations = False
        limits.max_critic_iterations = 5
        mock_limits.return_value = limits

        project = MagicMock()
        project.id = project_id
        project.channel_id = uuid.uuid4()
        project.theme = "Test"
        project.target_duration_seconds = 60
        project.config = {}
        project.status = "pending"

        channel = MagicMock()
        channel.id = project.channel_id
        channel.slug = "test"
        channel.theme_category = "science"
        channel.niche_prompt = ""
        channel.name = "Test Channel"
        channel.max_concurrent_pipelines = 1
        channel.user_id = uuid.uuid4()

        orch._get_project = AsyncMock(return_value=project)
        orch._get_channel = AsyncMock(return_value=channel)

        from agent.core.channel_config import ChannelRuntimeConfig

        channel_config = ChannelRuntimeConfig(production_mode="mixed")
        with patch(
            "agent.core.orchestrator.resolve_channel_config", return_value=channel_config
        ):
            await orch.run_pipeline(project_id)

    mock_shorts_only.assert_awaited_once()
    mock_exports.assert_awaited_once()
    mock_creation.assert_not_awaited()
    mock_clipper_pipeline.assert_not_awaited()
    mock_thumbnail.assert_not_awaited()


@pytest.mark.asyncio
async def test_shorts_only_runs_hook_optimizer_in_pre_media() -> None:
    from agent.core.channel_config import ChannelRuntimeConfig
    from agent.core.database import Scenario
    from agent.core.orchestrator import Orchestrator

    orch = Orchestrator()
    ctx = MagicMock()
    ctx.project_id = uuid.uuid4()
    ctx.channel_config = ChannelRuntimeConfig(production_mode="shorts_only")
    ctx.is_short_project = True
    ctx.channel_config.max_fact_check_iterations = 1

    scenario = MagicMock(spec=Scenario)
    pid = str(ctx.project_id)

    hook_optimizer = AsyncMock()
    hook_optimizer.run = AsyncMock(return_value=scenario)
    fact_checker = AsyncMock()
    fact_checker.run = AsyncMock(return_value=MagicMock(passed=True, warnings=[]))

    with patch(
        "agent.core.orchestrator._agent",
    ) as mock_agent_factory, patch(
        "agent.core.orchestrator.queue.set_agent_status", new_callable=AsyncMock
    ) as mock_status:
        def factory(cls, ctx):
            name = getattr(cls, "name", "")
            if name == "hook_optimizer_agent":
                return hook_optimizer
            return fact_checker

        mock_agent_factory.side_effect = factory

        result = await orch._run_pre_media_quality_agents(ctx, scenario, pid)

    assert result is scenario
    hook_optimizer.run.assert_awaited_once()
    hook_status_calls = [
        call for call in mock_status.await_args_list
        if len(call.args) >= 3 and call.args[1] == "hook_optimizer_agent"
    ]
    assert any(call.args[2] == "success" for call in hook_status_calls)
    fact_checker.run.assert_awaited_once()
