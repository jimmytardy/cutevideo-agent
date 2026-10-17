"""Graph API Instagram : une seule version, surchargeable par INSTAGRAM_GRAPH_API_VERSION (agent/skills/publisher/graph_api.py)."""

from __future__ import annotations

import pytest

from agent.skills.publisher import graph_api


def test_graph_api_url_uses_default_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INSTAGRAM_GRAPH_API_VERSION", raising=False)
    assert graph_api.graph_api_url("123/media") == (
        f"https://graph.facebook.com/{graph_api.GRAPH_API_DEFAULT_VERSION}/123/media"
    )
    assert graph_api._VERSION_RE.match(graph_api.GRAPH_API_DEFAULT_VERSION)


def test_graph_api_url_env_override_and_leading_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSTAGRAM_GRAPH_API_VERSION", "v99.0")
    assert graph_api.graph_api_url("/me") == "https://graph.facebook.com/v99.0/me"


@pytest.mark.parametrize("raw", ["  ", "26.0", "v26", "v26.0/", "latest"])
def test_malformed_env_version_falls_back_to_default(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("INSTAGRAM_GRAPH_API_VERSION", raw)
    assert graph_api.graph_api_version() == graph_api.GRAPH_API_DEFAULT_VERSION
