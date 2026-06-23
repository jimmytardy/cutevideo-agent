"""Tests annulation pipeline via watcher Redis dans le worker."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from scripts import pipeline_worker


@pytest.mark.asyncio
async def test_cancel_watcher_cancels_pipeline_task() -> None:
    project_id = uuid.uuid4()
    pipeline_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(60))
    stop = asyncio.Event()

    with patch.object(
        pipeline_worker.queue,
        "is_pipeline_cancel_requested",
        new=AsyncMock(return_value=True),
    ):
        await pipeline_worker._cancel_watcher(project_id, pipeline_task, stop)

    assert pipeline_task.cancelled() or pipeline_task.cancelling()


@pytest.mark.asyncio
async def test_cancel_watcher_stops_when_pipeline_done() -> None:
    project_id = uuid.uuid4()
    pipeline_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(0))
    stop = asyncio.Event()

    with patch.object(
        pipeline_worker.queue,
        "is_pipeline_cancel_requested",
        new=AsyncMock(return_value=False),
    ):
        await pipeline_worker._cancel_watcher(project_id, pipeline_task, stop)

    assert pipeline_task.done()
    assert not pipeline_task.cancelled()
