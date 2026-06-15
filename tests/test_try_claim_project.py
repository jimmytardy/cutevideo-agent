from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.concurrency import try_claim_project


@pytest.mark.asyncio
async def test_try_claim_project_returns_false_when_no_row_updated() -> None:
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()

    with patch("agent.core.concurrency.AsyncSessionFactory") as mock_factory:
        session = AsyncMock()
        channel_result = AsyncMock()
        channel_result.scalar_one_or_none = MagicMock(return_value=1)
        update_result = MagicMock()
        update_result.rowcount = 0
        session.execute = AsyncMock(side_effect=[channel_result, update_result])
        session.commit = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = session

        claimed = await try_claim_project(project_id, channel_id)

    assert claimed is False


@pytest.mark.asyncio
async def test_try_claim_project_returns_true_when_updated() -> None:
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()

    with patch("agent.core.concurrency.AsyncSessionFactory") as mock_factory:
        session = AsyncMock()
        channel_result = AsyncMock()
        channel_result.scalar_one_or_none = MagicMock(return_value=1)
        update_result = MagicMock()
        update_result.rowcount = 1
        session.execute = AsyncMock(side_effect=[channel_result, update_result])
        session.commit = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = session

        claimed = await try_claim_project(project_id, channel_id)

    assert claimed is True
