from __future__ import annotations

from agent.skills.market_research.youtube_discovery import search_queries_from_prompt


def test_search_queries_dedup() -> None:
    queries = search_queries_from_prompt("histoire de France médiévale")
    assert len(queries) >= 1
    assert len(queries) == len(set(q.lower() for q in queries))
