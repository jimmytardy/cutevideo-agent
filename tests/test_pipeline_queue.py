from __future__ import annotations

from agent.core.pipeline_queue import MAX_QUEUE_PRIORITY, compute_queue_score


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
