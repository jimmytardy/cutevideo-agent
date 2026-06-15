from __future__ import annotations

from agent.agents.critic_agent import CriticAgent


def test_build_video_analysis_dict_ok_status() -> None:
    from agent.agents.video_analyst_agent import VideoAnalysis

    analysis = VideoAnalysis(
        score=80,
        issues=[],
        visual_coherence=20,
        subtitle_quality=22,
        rhythm=18,
        summary="OK",
    )
    data = CriticAgent._build_video_analysis_dict(analysis, "ok")
    assert data["analysis_status"] == "ok"
    assert data["score"] == 80


def test_build_video_analysis_dict_unavailable() -> None:
    data = CriticAgent._build_video_analysis_dict(None, "missing_key")
    assert data["analysis_status"] == "missing_key"
    assert data["score"] == 0
