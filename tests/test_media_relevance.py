"""Tests pertinence média."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent.agents.media_agent import MediaAgent
from agent.skills.media.ai_image_result import AiImageResult
from agent.skills.media_sources.relevance_scorer import MediaRelevanceScoringError, ScoredCandidate


def test_build_anchored_queries_includes_video_subject() -> None:
    queries = MediaAgent._build_anchored_queries(
        ["rouge-gorge", "European robin"],
        "Le rouge-gorge familier",
        "Habitat",
    )
    assert any("Le rouge-gorge familier" in q for q in queries)
    assert queries[0] == ["rouge-gorge", "European robin"]


def test_build_anchored_queries_fallback_to_subject_only() -> None:
    queries = MediaAgent._build_anchored_queries([], "Napoléon à Waterloo", "La bataille")
    assert queries == [["Napoléon à Waterloo"]]


def test_select_assets_prioritizes_video() -> None:
    candidates = [
        {"asset_type": "image", "url": "img1"},
        {"asset_type": "video", "url": "vid1"},
        {"asset_type": "video", "url": "vid2"},
        {"asset_type": "image", "url": "img2"},
        {"asset_type": "image", "url": "img3"},
    ]
    selected = MediaAgent._select_assets(candidates, video_target=1, total_needed=4)
    assert len(selected) == 4
    assert selected[0]["asset_type"] == "video"


@pytest.mark.asyncio
async def test_score_media_candidates_raises_without_api_key() -> None:
    from agent.skills.media_sources.relevance_scorer import score_media_candidates

    with pytest.raises(MediaRelevanceScoringError, match="GOOGLE_GEMINI_API_KEY"):
        await score_media_candidates(
            [{"url": "http://img", "title": "test"}],
            video_subject="Sujet",
            channel_category="nature",
            segment_title="Segment",
            segment_narration="Narration",
            api_key="",
        )


def _make_agent_ctx(tmp_path: Path) -> tuple[MediaAgent, object, dict, object]:
    agent = MediaAgent()
    agent._relevance_log = []
    agent._kept_temp_s3_keys = []
    ctx = type("Ctx", (), {
        "theme": "Sujet",
        "theme_category": "nature",
        "project_id": "00000000-0000-0000-0000-000000000001",
        "channel": type("Ch", (), {"slug": "test-channel"})(),
        "channel_config": type("C", (), {"editorial_tone": ""})(),
    })()
    segment = {"order": 1, "title": "Segment", "narration_text": "Narration"}
    ai_cfg = type("Ai", (), {"enabled": True, "plan": type("P", (), {"value": "flux_pro"})()})()
    return agent, ctx, segment, ai_cfg


@pytest.mark.asyncio
async def test_generate_validated_ai_image_forced_best_on_low_scores(tmp_path: Path) -> None:
    agent, ctx, segment, ai_cfg = _make_agent_ctx(tmp_path)
    ai_path = tmp_path / "ai.png"
    ai_path.write_bytes(b"png")
    ai_item = {
        "source": "ai_image",
        "url": str(ai_path),
        "local_generated": str(ai_path),
        "title": "IA test",
    }
    from agent.core.media_validation import MediaValidationBrief

    brief = MediaValidationBrief(min_relevance_score=60)

    async def fake_score(candidates, **kwargs):
        return [ScoredCandidate(candidate=c, score=40, reason="hors sujet") for c in candidates]

    with (
        patch(
            "agent.agents.media_agent.ai_fallback_attempt_config",
            return_value=("flux_2_dev", 1, 1),
        ),
        patch(
            "agent.skills.media_sources.relevance_scorer.score_media_candidates",
            new=AsyncMock(side_effect=fake_score),
        ),
        patch.object(MediaAgent, "_generate_ai_fallback", new=AsyncMock(return_value=ai_item)),
        patch.object(MediaAgent, "_upload_ai_candidate_temp", new=AsyncMock(return_value=None)),
    ):
        result = await agent._generate_validated_ai_image(
            "prompt",
            tmp_path,
            ctx,
            segment,
            60,
            ai_cfg,
            "16:9",
            brief,
        )

    assert result.outcome == "forced_best"
    assert result.item is not None
    assert result.item.get("_relevance_forced_fallback") is True


@pytest.mark.asyncio
async def test_generate_validated_ai_image_api_failed(tmp_path: Path) -> None:
    agent, ctx, segment, ai_cfg = _make_agent_ctx(tmp_path)
    from agent.core.media_validation import MediaValidationBrief

    brief = MediaValidationBrief(min_relevance_score=60)

    with (
        patch(
            "agent.agents.media_agent.ai_fallback_attempt_config",
            return_value=("flux_2_dev", 1, 1),
        ),
        patch.object(MediaAgent, "_generate_ai_fallback", new=AsyncMock(return_value=None)),
    ):
        result = await agent._generate_validated_ai_image(
            "prompt",
            tmp_path,
            ctx,
            segment,
            60,
            ai_cfg,
            "16:9",
            brief,
        )

    assert result.outcome == "api_failed"
    assert result.item is None


@pytest.mark.asyncio
async def test_generate_validated_ai_image_validated_on_second_phase(tmp_path: Path) -> None:
    agent, ctx, segment, ai_cfg = _make_agent_ctx(tmp_path)
    ai_path = tmp_path / "ai.jpg"
    ai_path.write_bytes(b"jpg")
    ai_item = {
        "source": "ai_image",
        "url": str(ai_path),
        "local_generated": str(ai_path),
        "title": "IA test",
    }
    from agent.core.media_validation import MediaValidationBrief

    brief = MediaValidationBrief(min_relevance_score=60)
    scores = [40, 75]

    async def fake_score(candidates, **kwargs):
        score = scores.pop(0)
        return [ScoredCandidate(candidate=c, score=score, reason="ok" if score >= 60 else "bad") for c in candidates]

    with (
        patch(
            "agent.agents.media_agent.ai_fallback_attempt_config",
            return_value=("flux_2_dev", 1, 1),
        ),
        patch(
            "agent.skills.media_sources.relevance_scorer.score_media_candidates",
            new=AsyncMock(side_effect=fake_score),
        ),
        patch.object(MediaAgent, "_generate_ai_fallback", new=AsyncMock(return_value=ai_item)),
        patch.object(MediaAgent, "_upload_ai_candidate_temp", new=AsyncMock(return_value=None)),
    ):
        result = await agent._generate_validated_ai_image(
            "prompt",
            tmp_path,
            ctx,
            segment,
            60,
            ai_cfg,
            "16:9",
            brief,
        )

    assert result.outcome == "validated"
    assert result.item is not None
    assert result.item.get("_relevance_validated") is True


@pytest.mark.asyncio
async def test_apply_ai_image_result_records_gap() -> None:
    agent = MediaAgent()
    agent._media_gaps = []
    agent._segment_media_gaps = set()
    agent._ai_images_used = 0
    ctx = type("Ctx", (), {"channel_config": type("C", (), {"timezone": "Europe/Paris"})(), "channel_id": "x"})()
    segment = {"order": 2}
    selected: list[dict] = []

    await agent._apply_ai_image_result(
        AiImageResult(outcome="api_failed"),
        ctx=ctx,
        segment=segment,
        ai_prompt="test prompt",
        selected=selected,
        dev_attempts=3,
        paid_attempts=3,
    )

    assert len(agent._media_gaps) == 1
    assert agent._media_gaps[0].segment_order == 2
    assert selected == []
