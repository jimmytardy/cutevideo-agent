"""Tests YouTube discovery."""

from __future__ import annotations

from agent.skills.market_research.youtube_discovery import (
    resolve_youtube_channel_id,
    search_queries_from_prompt,
)


def test_search_queries_dedup() -> None:
    queries = search_queries_from_prompt("histoire de France médiévale")
    assert len(queries) >= 1
    assert len(queries) == len(set(q.lower() for q in queries))


def test_resolve_youtube_channel_id() -> None:
    cid = "UCabcdefghijklmnopqr12st"
    assert resolve_youtube_channel_id(cid) == cid
    assert resolve_youtube_channel_id(f"https://www.youtube.com/channel/{cid}") == cid
    assert resolve_youtube_channel_id("https://www.youtube.com/@Histoir") == "@Histoir"
    assert resolve_youtube_channel_id("@foo") == "@foo"
    assert resolve_youtube_channel_id("") is None
