from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.project_cost import project_cost_breakdown


@pytest.mark.asyncio
async def test_cost_breakdown_uses_claude_studio_session_cost() -> None:
    project = SimpleNamespace(config={"claude_studio": {"status": "approved", "cost_usd": 1.25}})
    runs = MagicMock()
    runs.scalars.return_value.all.return_value = []
    with patch("agent.core.project_cost.AsyncSessionFactory") as factory:
        session = AsyncMock()
        session.get = AsyncMock(return_value=project)
        session.execute = AsyncMock(return_value=runs)
        factory.return_value.__aenter__.return_value = session

        breakdown = await project_cost_breakdown(uuid.uuid4(), cap_usd=5.0)

    assert breakdown.total_usd == 1.25
    assert breakdown.stop_reason == "approved"
    assert [row.agent_name for row in breakdown.by_agent] == ["claude_studio"]
