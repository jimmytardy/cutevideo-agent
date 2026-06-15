from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.concurrency import can_start_pipeline


@pytest.mark.asyncio
async def test_can_start_pipeline_excludes_current_project() -> None:
    channel_id = uuid.uuid4()
    project_id = uuid.uuid4()

    with patch(
        "agent.core.concurrency.count_running_pipelines",
        new_callable=AsyncMock,
        return_value=0,
    ) as mock_count, patch(
        "agent.core.concurrency.AsyncSessionFactory"
    ) as mock_factory:
        session = AsyncMock()
        result = AsyncMock()
        result.scalar_one_or_none = MagicMock(return_value=1)
        session.execute = AsyncMock(return_value=result)
        mock_factory.return_value.__aenter__.return_value = session

        allowed = await can_start_pipeline(
            channel_id, exclude_project_id=project_id
        )

    assert allowed is True
    mock_count.assert_awaited_once_with(
        channel_id, exclude_project_id=project_id
    )
