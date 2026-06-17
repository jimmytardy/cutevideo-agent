from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.pipeline_queue import (
    MAX_QUEUE_PRIORITY,
    PIPELINE_ZQUEUE,
    _payload_key,
    compute_queue_score,
)


def test_compute_queue_score_higher_priority_first() -> None:
    t = 1_700_000_000_000
    pro_score = compute_queue_score(30, t)
    free_score = compute_queue_score(10, t + 1000)
    assert pro_score < free_score


def test_compute_queue_score_fifo_within_same_priority() -> None:
    priority = 20
    earlier = compute_queue_score(priority, 1_700_000_000_000)
    later = compute_queue_score(priority, 1_700_000_000_500)
    assert earlier < later


def test_compute_queue_score_clamps_priority() -> None:
    score = compute_queue_score(999, 1_700_000_000_000)
    max_score = compute_queue_score(MAX_QUEUE_PRIORITY, 1_700_000_000_000)
    assert score == max_score


def _mock_session_factory(session: AsyncMock) -> MagicMock:
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=session)
    factory.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.mark.asyncio
async def test_prune_removes_orphan_keeps_queued() -> None:
    """Un membre dont le projet est supprimé est purgé ; le projet queued reste."""
    from agent.core.pipeline_queue import prune_orphan_queue_entries

    orphan_id = uuid.uuid4()
    valid_id = uuid.uuid4()
    members = [str(orphan_id), str(valid_id)]

    # La DB ne connaît que le projet valide (queued) ; l'orphelin est absent.
    db_result = MagicMock()
    db_result.all.return_value = [SimpleNamespace(id=valid_id, status="queued")]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=db_result)

    mock_redis = AsyncMock()
    mock_redis.zrange = AsyncMock(return_value=members)
    mock_redis.zrem = AsyncMock()
    mock_redis.delete = AsyncMock()

    with (
        patch(
            "agent.core.pipeline_queue.AsyncSessionFactory",
            return_value=_mock_session_factory(session),
        ),
        patch("agent.core.pipeline_queue.queue") as mock_queue,
    ):
        mock_queue.connect = AsyncMock()
        mock_queue.client = mock_redis
        pruned = await prune_orphan_queue_entries()

    assert pruned == 1
    mock_redis.zrem.assert_awaited_once_with(PIPELINE_ZQUEUE, str(orphan_id))
    mock_redis.delete.assert_awaited_once_with(_payload_key(str(orphan_id)))


@pytest.mark.asyncio
async def test_prune_removes_non_queued_status() -> None:
    """Un membre dont le projet n'est plus « queued » (ex. stopped) est purgé."""
    from agent.core.pipeline_queue import prune_orphan_queue_entries

    stopped_id = uuid.uuid4()
    db_result = MagicMock()
    db_result.all.return_value = [SimpleNamespace(id=stopped_id, status="stopped")]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=db_result)

    mock_redis = AsyncMock()
    mock_redis.zrange = AsyncMock(return_value=[str(stopped_id)])
    mock_redis.zrem = AsyncMock()
    mock_redis.delete = AsyncMock()

    with (
        patch(
            "agent.core.pipeline_queue.AsyncSessionFactory",
            return_value=_mock_session_factory(session),
        ),
        patch("agent.core.pipeline_queue.queue") as mock_queue,
    ):
        mock_queue.connect = AsyncMock()
        mock_queue.client = mock_redis
        pruned = await prune_orphan_queue_entries()

    assert pruned == 1
    mock_redis.zrem.assert_awaited_once_with(PIPELINE_ZQUEUE, str(stopped_id))


@pytest.mark.asyncio
async def test_dequeue_drops_orphan_without_reenqueue() -> None:
    """Un projet supprimé poppé de la file est abandonné, jamais ré-enfilé."""
    from agent.core.pipeline_queue import dequeue_next_eligible

    orphan_id = uuid.uuid4()
    channel_id = uuid.uuid4()

    # session.get(Project, id) → None : le projet n'existe plus.
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

    mock_redis = AsyncMock()
    # Premier pop : l'orphelin. Second pop : file vide → on sort.
    mock_redis.zpopmin = AsyncMock(side_effect=[[(str(orphan_id), 1.0)], []])
    mock_redis.delete = AsyncMock()

    with (
        patch(
            "agent.core.pipeline_queue.get_pipeline_settings",
            return_value=MagicMock(queue_dequeue_max_attempts=50),
        ),
        patch(
            "agent.core.pipeline_queue.AsyncSessionFactory",
            return_value=_mock_session_factory(session),
        ),
        patch("agent.core.pipeline_queue.queue") as mock_queue,
        patch(
            "agent.core.pipeline_queue._load_payload",
            new=AsyncMock(return_value={"channel_id": str(channel_id)}),
        ),
        patch(
            "agent.core.pipeline_queue.reenqueue_with_same_score",
            new=AsyncMock(),
        ) as mock_reenqueue,
        patch(
            "agent.core.pipeline_queue.try_claim_project",
            new=AsyncMock(return_value=True),
        ) as mock_claim,
    ):
        mock_queue.connect = AsyncMock()
        mock_queue.client = mock_redis
        result = await dequeue_next_eligible()

    assert result.payload is None
    mock_reenqueue.assert_not_awaited()
    mock_claim.assert_not_awaited()
    mock_redis.delete.assert_awaited_once_with(_payload_key(str(orphan_id)))
