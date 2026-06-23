"""Tests parallélisme beats media_agent."""

from __future__ import annotations

import os
from unittest.mock import patch

from agent.core.concurrency import beat_fanout_concurrency, fanout_concurrency


def test_beat_fanout_default_is_at_least_six() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MEDIA_BEAT_FANOUT_CONCURRENCY", None)
        os.environ.pop("PIPELINE_FANOUT_CONCURRENCY", None)
        assert beat_fanout_concurrency() >= 6


def test_beat_fanout_respects_env_override() -> None:
    with patch.dict(os.environ, {"MEDIA_BEAT_FANOUT_CONCURRENCY": "4"}):
        assert beat_fanout_concurrency() == 4


def test_beat_fanout_scales_with_segment_fanout_when_unset() -> None:
    with patch.dict(os.environ, {"PIPELINE_FANOUT_CONCURRENCY": "5"}, clear=False):
        os.environ.pop("MEDIA_BEAT_FANOUT_CONCURRENCY", None)
        assert beat_fanout_concurrency() == max(fanout_concurrency() * 2, 6)
