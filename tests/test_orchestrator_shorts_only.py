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
    ) as mock_native, patch(
        "agent.core.storage.cleanup_local_videos_for_project", new_callable=AsyncMock
    ) as mock_cleanup, patch(
        "agent.core.storage.cleanup_temp_ai_images", new_callable=AsyncMock
    ), patch.object(
        orch, "_update_project_status", new_callable=AsyncMock
    ), patch(
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
