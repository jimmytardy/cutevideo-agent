"""Garde-fous coût et itérations (build 09)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.agents.critic_agent import CriticAgent
from agent.agents.video_analyst_agent import VideoAnalysis
from agent.core.llm_usage import LlmUsageRecord, estimate_llm_cost_usd, load_pricing
from agent.core.quality_guardrails import resolve_effective_quality_iterations
from agent.core.segment_fingerprint import (
    compute_changed_segments,
    segment_scenario_fingerprint,
)
from agent.core.subscription import SubscriptionLimits
from agent.skills.video.segment_video_analysis import merge_video_analyses


def test_resolve_effective_quality_iterations_min_of_caps() -> None:
    limits = SubscriptionLimits(max_critic_iterations=5)
    assert resolve_effective_quality_iterations(
        project_config={},
        channel_quality_max=3,
        channel_critic_max=5,
        limits=limits,
    ) == 3

    limits_free = SubscriptionLimits(max_critic_iterations=2)
    assert resolve_effective_quality_iterations(
        project_config={"max_critic_iterations": 10},
        channel_quality_max=5,
        channel_critic_max=5,
        limits=limits_free,
    ) == 2


def test_resolve_effective_quality_iterations_admin_still_capped_by_quality() -> None:
    limits = SubscriptionLimits(unlimited_critic_iterations=True)
    assert resolve_effective_quality_iterations(
        project_config={},
        channel_quality_max=3,
        channel_critic_max=20,
        limits=limits,
    ) == 3


def test_estimate_llm_cost_usd_from_pricing() -> None:
    pricing = load_pricing()
    assert "claude-sonnet-4-5" in pricing
    cost = estimate_llm_cost_usd("claude-sonnet-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0, rel=0.01)


def test_finalize_decision_forces_approve_at_cap() -> None:
    decision, data = CriticAgent._finalize_decision(
        decision="iterate",
        data={"requested_changes": [{"agent": "editor_agent"}], "feedback": {}},
        iteration=3,
        max_iterations=3,
    )
    assert decision == "approve"
    assert data["requested_changes"] == []


def test_routing_override_respects_iteration_cap() -> None:
    from agent.core.channel_config import ChannelRuntimeConfig

    ctx = MagicMock()
    ctx.channel_config = ChannelRuntimeConfig(max_static_shot_s=8)
    data = {"requested_changes": [], "feedback": {"rhythm": 3, "dynamism": 3, "visual_quality": 5}}
    out_data, decision, _ = CriticAgent._apply_routing_overrides(
        data, "approve", "editor_agent", None, ctx, at_iteration_cap=True,
    )
    assert decision == "approve"
    assert out_data is data


def test_merge_video_analyses_reweights_score() -> None:
    previous = VideoAnalysis(
        score=70,
        issues=[{"type": "visual", "severity": "low", "timestamp_s": 50, "description": "old"}],
        visual_coherence=15,
        subtitle_quality=15,
        rhythm=15,
        summary="prev",
    )
    partial = VideoAnalysis(
        score=90,
        issues=[{"type": "visual", "severity": "high", "timestamp_s": 2, "description": "new"}],
        visual_coherence=20,
        subtitle_quality=20,
        rhythm=20,
        summary="new seg",
    )
    merged = merge_video_analyses(
        previous,
        {1: partial},
        segment_durations={1: 10.0, 2: 10.0},
        segment_offsets={1: 0.0, 2: 10.0},
    )
    assert merged.score > 70
    assert any(i["timestamp_s"] == 2 for i in merged.issues)


@pytest.mark.asyncio
async def test_compute_changed_segments_detects_diff() -> None:
    seg_a = {"order": 1, "narration": "hello"}
    seg_b = {"order": 1, "narration": "changed"}

    fp_a = segment_scenario_fingerprint(seg_a)
    fp_b = segment_scenario_fingerprint(seg_b)
    assert fp_a != fp_b

    project_id = uuid.uuid4()

    async def fake_fingerprints(_pid: uuid.UUID, iteration: int) -> dict[int, str]:
        if iteration == 1:
            return {1: "aaa", 2: "bbb"}
        return {1: "ccc", 2: "bbb"}

    with patch(
        "agent.core.segment_fingerprint.compute_segment_fingerprints",
        side_effect=fake_fingerprints,
    ):
        changed = await compute_changed_segments(project_id, 2)
    assert changed == {1}


@pytest.mark.asyncio
async def test_project_cost_exceeded() -> None:
    from agent.core.project_cost import project_cost_exceeded

    with patch(
        "agent.core.project_cost.sum_project_llm_cost_usd",
        new_callable=AsyncMock,
        return_value=9.5,
    ):
        assert await project_cost_exceeded(uuid.uuid4(), 8.0) is True
        assert await project_cost_exceeded(uuid.uuid4(), 0.0) is False


@pytest.mark.asyncio
async def test_record_llm_usage_on_end_run() -> None:
    from agent.core.base_agent import BaseAgent
    from agent.core.database import AgentRun
    from agent.core.llm_usage import record_llm_usage, start_run_usage_tracking

    class _DummyAgent(BaseAgent):
        name = "dummy_agent"

        async def run(self, input_data: object) -> object:
            return input_data

    agent = _DummyAgent()
    run = AgentRun(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        agent_name="dummy_agent",
        status="running",
        iteration=1,
    )

    start_run_usage_tracking()
    record_llm_usage(LlmUsageRecord("claude-sonnet-4-5", 1000, 500, 0.01))

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=run)
    mock_session.commit = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_cm.__aexit__.return_value = None

    with patch("agent.core.base_agent.AsyncSessionFactory", return_value=mock_cm):
        await agent._persist_run_usage(run)

    assert run.cost_estimate_usd == 0.01
    assert run.llm_input_tokens == 1000


def test_promote_best_video_logic_scores() -> None:
    """Simule la sélection meilleure itération (orchestrateur)."""
    scores = [(uuid.uuid4(), 70), (uuid.uuid4(), 85), (uuid.uuid4(), 60)]
    best_score = 0
    best_id = None
    for vid, score in scores:
        if score > best_score:
            best_score = score
            best_id = vid
    assert best_score == 85
    assert best_id == scores[1][0]
