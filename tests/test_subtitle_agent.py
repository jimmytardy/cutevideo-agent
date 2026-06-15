"""Tests SubtitleAgent — fallback audio et burn-in shorts."""

from __future__ import annotations

from agent.agents.subtitle_agent import SubtitleAgent
from agent.core.channel_config import ChannelRuntimeConfig, SubtitleConfig


def test_should_burn_in_short_platform_in_shorts_only() -> None:
    ctx = type("Ctx", (), {
        "channel_config": ChannelRuntimeConfig(
            production_mode="shorts_only",
            subtitles=SubtitleConfig(enabled=True),
        ),
    })()
    video = type("Video", (), {"video_type": "short_youtube"})()
    assert SubtitleAgent._should_burn_in(ctx, video) is True


def test_should_not_burn_in_long_in_shorts_only() -> None:
    ctx = type("Ctx", (), {
        "channel_config": ChannelRuntimeConfig(
            production_mode="shorts_only",
            subtitles=SubtitleConfig(enabled=True),
        ),
    })()
    video = type("Video", (), {"video_type": "long"})()
    assert SubtitleAgent._should_burn_in(ctx, video) is False


def test_should_not_burn_in_when_subtitles_disabled() -> None:
    ctx = type("Ctx", (), {
        "channel_config": ChannelRuntimeConfig(
            production_mode="shorts_only",
            subtitles=SubtitleConfig(enabled=False),
        ),
    })()
    video = type("Video", (), {"video_type": "short_master"})()
    assert SubtitleAgent._should_burn_in(ctx, video) is False
