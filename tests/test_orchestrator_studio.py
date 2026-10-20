"""L'orchestrateur délègue la création à Claude Studio puis approuve le projet."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.orchestrator import Orchestrator


def _project_and_channel() -> tuple[MagicMock, MagicMock]:
    project = MagicMock()
    project.id = uuid.uuid4()
    project.channel_id = uuid.uuid4()
    project.theme = "Les volcans"
    project.target_duration_seconds = None
    project.config = {"content_plan": {"angle": "x"}}
    project.status = "running"
    channel = MagicMock()
    channel.id = project.channel_id
    channel.user_id = uuid.uuid4()
    channel.slug = "test"
    channel.theme_category = "science"
    channel.niche_prompt = "vulgarisation"
    return project, channel


@pytest.mark.asyncio
async def test_run_pipeline_uses_claude_studio_and_approves() -> None:
    orch = Orchestrator()
    project, channel = _project_and_channel()
    orch._get_project = AsyncMock(return_value=project)
    orch._get_channel = AsyncMock(return_value=channel)
    runner = MagicMock()
    runner.return_value.run = AsyncMock()

    with patch("agent.core.orchestrator.AsyncSessionFactory") as factory, patch(
        "agent.core.orchestrator._raise_if_cancelled", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.resolve_user_limits", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.resolve_channel_config",
        return_value=ChannelRuntimeConfig(short_duration_s=45),
    ), patch(
        "agent.core.orchestrator.resolve_effective_max_critic_iterations", return_value=3
    ), patch.object(
        orch, "_update_project_status", new_callable=AsyncMock
    ) as update_status, patch(
        "agent.core.claude_studio.ClaudeStudioRunner", runner
    ), patch(
        "agent.core.storage.cleanup_local_videos_for_project", new_callable=AsyncMock
    ):
        factory.return_value.__aenter__.return_value = AsyncMock()
        await orch.run_pipeline(project.id, already_claimed=True)

    ctx = runner.call_args.args[0]
    assert ctx.target_duration_seconds == 45
    assert ctx.max_critic_iterations == 3
    assert ctx.content_plan == {"angle": "x"}
    runner.return_value.run.assert_awaited_once()
    assert update_status.await_args.args[2] == "approved"


@pytest.mark.parametrize(("cancel_requested", "expected"), [(False, "running"), (True, "stopped")])
@pytest.mark.asyncio
async def test_interrupted_creation_yields_to_a_concurrent_stop(
    cancel_requested: bool, expected: str
) -> None:
    """Une interruption laisse le projet `running` pour qu'il reprenne — sauf si « Arrêter » a été cliqué
    entre-temps, auquel cas repasser à `running` relancerait une création que l'utilisateur a arrêtée."""
    from agent.core.studio_resume import STALL_MESSAGE, StudioInterrupted

    orch = Orchestrator()
    project, channel = _project_and_channel()
    orch._get_project = AsyncMock(return_value=project)
    orch._get_channel = AsyncMock(return_value=channel)
    runner = MagicMock()
    runner.return_value.run = AsyncMock(side_effect=StudioInterrupted(STALL_MESSAGE))

    with patch("agent.core.orchestrator.AsyncSessionFactory") as factory, patch(
        "agent.core.orchestrator._raise_if_cancelled", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.resolve_user_limits", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.resolve_channel_config",
        return_value=ChannelRuntimeConfig(short_duration_s=45),
    ), patch(
        "agent.core.orchestrator.resolve_effective_max_critic_iterations", return_value=3
    ), patch.object(
        orch, "_update_project_status", new_callable=AsyncMock
    ) as update_status, patch(
        "agent.core.claude_studio.ClaudeStudioRunner", runner
    ), patch(
        "agent.core.orchestrator.stop_running_agent_runs", new_callable=AsyncMock
    ), patch(
        "agent.core.storage.cleanup_local_videos_for_project", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.queue.is_pipeline_cancel_requested",
        new_callable=AsyncMock,
        return_value=cancel_requested,
    ):
        factory.return_value.__aenter__.return_value = AsyncMock()
        await orch.run_pipeline(project.id, already_claimed=True)

    assert update_status.await_args.args[2] == expected


@pytest.mark.asyncio
async def test_run_pipeline_marks_failed_when_studio_fails() -> None:
    orch = Orchestrator()
    project, channel = _project_and_channel()
    orch._get_project = AsyncMock(return_value=project)
    orch._get_channel = AsyncMock(return_value=channel)
    runner = MagicMock()
    runner.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("agent.core.orchestrator.AsyncSessionFactory") as factory, patch(
        "agent.core.orchestrator._raise_if_cancelled", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.resolve_user_limits", new_callable=AsyncMock
    ), patch(
        "agent.core.orchestrator.resolve_channel_config", return_value=ChannelRuntimeConfig()
    ), patch(
        "agent.core.orchestrator.resolve_effective_max_critic_iterations", return_value=2
    ), patch.object(
        orch, "_update_project_status", new_callable=AsyncMock
    ) as update_status, patch(
        "agent.core.claude_studio.ClaudeStudioRunner", runner
    ):
        factory.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(RuntimeError, match="boom"):
            await orch.run_pipeline(project.id, already_claimed=True)

    assert update_status.await_args.args[2] == "failed"
