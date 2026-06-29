"""Tests StyleDirectorAgent (collecte sans réseau)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from agent.agents.style_director_agent import StyleDirectorAgent
from agent.core.database import Channel


@pytest.mark.asyncio
async def test_run_for_channel_no_references_skips_update() -> None:
    channel_id = uuid.uuid4()
    channel = Channel(
        id=channel_id,
        user_id=uuid.uuid4(),
        slug="test-style",
        name="Test",
        config={},
        is_active=True,
    )

    agent = StyleDirectorAgent()

    with patch.object(agent, "_collect_reference_urls", new_callable=AsyncMock, return_value=[]):
        with patch("agent.agents.style_director_agent.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__.return_value = mock_session
            mock_session.get.return_value = channel

            result = await agent.run_for_channel(channel_id, force=True)

    assert result.get("skipped") is True
    assert result.get("reason") == "no_references"
    mock_session.commit.assert_not_called()
