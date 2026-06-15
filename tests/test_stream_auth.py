"""Tests auth streams média, middleware query token et normalisation feedback critique."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from agent.agents.critic_agent import CriticAgent
from agent.core.database import User
from api.authorization import get_user_project
from api.middleware_auth import resolve_request_auth_token


def _make_request(
    path: str,
    *,
    authorization: str | None = None,
    query: str = "",
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": query.lstrip("?").encode(),
    }
    return Request(scope)


def test_resolve_request_auth_token_prefers_bearer_header() -> None:
    request = _make_request(
        "/api/v1/projects/x/stream",
        authorization="Bearer header-token",
        query="access_token=query-token",
    )
    assert resolve_request_auth_token(request) == "header-token"


def test_resolve_request_auth_token_falls_back_to_query() -> None:
    request = _make_request(
        "/api/v1/projects/x/stream",
        query="access_token=query-token",
    )
    assert resolve_request_auth_token(request) == "query-token"


def test_resolve_request_auth_token_returns_none_without_credentials() -> None:
    request = _make_request("/api/v1/projects/x/stream")
    assert resolve_request_auth_token(request) is None


@pytest.mark.asyncio
async def test_protected_route_returns_401_without_token() -> None:
    from httpx import ASGITransport, AsyncClient

    from api.main import app

    project_id = uuid.uuid4()
    video_id = uuid.uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/projects/{project_id}/videos/{video_id}/stream",
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentification requise"


def test_normalize_feedback_flattens_nested_criteria() -> None:
    raw = {
        "rhythm": {"score": 16, "comments": "Bon rythme"},
        "structure": 12,
        "comments": "Synthèse globale",
        "start_from": "media_agent",
    }
    normalized = CriticAgent._normalize_feedback(raw)
    assert normalized["rhythm"] == 16
    assert normalized["structure"] == 12
    assert normalized["start_from"] == "media_agent"
    assert "Synthèse globale" in normalized["comments"]
    assert "rhythm: Bon rythme" in normalized["comments"]


def test_extract_structure_score_from_nested_object() -> None:
    feedback = {"structure": {"score": 14, "comments": "Hook faible"}}
    assert CriticAgent._extract_structure_score(feedback) == 14


def test_normalize_criterion_value_handles_primitives() -> None:
    assert CriticAgent._normalize_criterion_value(18) == 18
    assert CriticAgent._normalize_criterion_value({"score": 9}) == 9
    assert CriticAgent._normalize_criterion_value("bad") is None


@pytest.mark.asyncio
async def test_get_user_project_returns_404_for_other_user() -> None:
    from fastapi import HTTPException

    other_user = User(id=uuid.uuid4(), email="other@test.com", is_active=True)
    project_id = uuid.uuid4()

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    with pytest.raises(HTTPException) as exc_info:
        await get_user_project(session, project_id, other_user)

    assert exc_info.value.status_code == 404
