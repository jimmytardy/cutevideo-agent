from __future__ import annotations

import json
import uuid

import pytest

from agent.core.queue import PIPELINE_QUEUE, queue


@pytest.mark.asyncio
async def test_pipeline_cancel_flag() -> None:
    await queue.connect()
    project_id = str(uuid.uuid4())
    try:
        assert await queue.is_pipeline_cancel_requested(project_id) is False
        await queue.request_pipeline_cancel(project_id)
        assert await queue.is_pipeline_cancel_requested(project_id) is True
        await queue.clear_pipeline_cancel(project_id)
        assert await queue.is_pipeline_cancel_requested(project_id) is False
    finally:
        await queue.clear_pipeline_cancel(project_id)
        await queue.disconnect()


@pytest.mark.asyncio
async def test_pipeline_queue_push_pop() -> None:
    await queue.connect()
    project_id = str(uuid.uuid4())
    payload = {"project_id": project_id, "start_from": None}
    try:
        await queue.push_task(PIPELINE_QUEUE, payload)
        task = await queue.pop_task(PIPELINE_QUEUE, timeout=1)
        assert task is not None
        assert task["project_id"] == project_id
        assert json.loads(json.dumps(task)) == task
    finally:
        await queue.disconnect()


@pytest.mark.asyncio
async def test_pipeline_queue_blpop_empty_returns_none() -> None:
    await queue.connect()
    empty_queue = f"cutevideo:test-empty:{uuid.uuid4()}"
    try:
        task = await queue.pop_task(empty_queue, timeout=1)
        assert task is None
    finally:
        await queue.disconnect()
