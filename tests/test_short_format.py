from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.short_format import (
    clamp_short_scenario_payload,
    clamp_short_total_duration,
    effective_short_max_duration_s,
    exceeds_short_duration_limit,
    requires_vertical_output,
    rescale_segment_durations,
)


def test_effective_short_max_duration_s_uses_target_and_channel_cap() -> None:
    cfg = ChannelRuntimeConfig(max_short_duration_s=120, short_duration_s=90)
    assert effective_short_max_duration_s(60, cfg) == 60
    assert effective_short_max_duration_s(150, cfg) == 120
    assert effective_short_max_duration_s(None, cfg) == 90


def test_clamp_short_scenario_payload_rescales_segments() -> None:
    cfg = ChannelRuntimeConfig(
        min_short_duration_s=45,
        max_short_duration_s=120,
        short_duration_s=60,
    )
    raw = {
        "total_duration_s": 120,
        "segments": [
            {"order": 1, "duration_s": 60},
            {"order": 2, "duration_s": 60},
        ],
    }
    out = clamp_short_scenario_payload(
        raw,
        target_duration_seconds=60,
        channel_config=cfg,
    )
    assert out["total_duration_s"] == 60
    assert sum(seg["duration_s"] for seg in out["segments"]) == 60


def test_rescale_segment_durations_leaves_short_totals() -> None:
    segments = [{"duration_s": 20}, {"duration_s": 30}]
    assert rescale_segment_durations(segments, max_total_s=60) == segments


def test_requires_vertical_output_short_project() -> None:
    ctx = MagicMock()
    ctx.is_short_project = True
    ctx.derivation_short_index = None
    assert requires_vertical_output(ctx) is True


def test_exceeds_short_duration_limit_with_tolerance() -> None:
    cfg = ChannelRuntimeConfig(max_short_duration_s=120)
    assert exceeds_short_duration_limit(60.0, target_duration_seconds=60, channel_config=cfg) is False
    assert exceeds_short_duration_limit(66.0, target_duration_seconds=60, channel_config=cfg) is True


def test_clamp_short_total_duration() -> None:
    assert clamp_short_total_duration(150, min_duration_s=60, max_duration_s=120, fallback=90) == 120
    assert clamp_short_total_duration(40, min_duration_s=60, max_duration_s=120, fallback=90) == 60
