"""Tests auth streams média, middleware query token et normalisation feedback critique."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from agent.core.database import User
from api.authorization import get_user_project
from api.middleware_auth import is_media_stream_path, resolve_request_auth_token


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
        "/api/v1/projects/x/studio/file",
        authorization="Bearer header-token",
        query="access_token=query-token",
    )
    assert resolve_request_auth_token(request) == ("header-token", "access")


def test_resolve_request_auth_token_accepts_media_token_in_query_on_stream_routes() -> None:
    request = _make_request("/api/v1/projects/x/studio/file", query="path=voice.wav&access_token=query-token")
    assert resolve_request_auth_token(request) == ("query-token", "media")


def test_resolve_request_auth_token_refuses_query_token_outside_stream_routes() -> None:
    request = _make_request("/api/v1/projects", query="access_token=query-token")
    assert resolve_request_auth_token(request) is None


def test_resolve_request_auth_token_returns_none_without_credentials() -> None:
    request = _make_request("/api/v1/projects/x/studio/file")
    assert resolve_request_auth_token(request) is None


@pytest.mark.parametrize("path, expected", [
    ("/api/v1/projects/11111111-1111-1111-1111-111111111111/videos/22222222-2222-2222-2222-222222222222/stream", True),
    ("/api/v1/projects/p/thumbnails/0/stream", True),
    ("/api/v1/projects/p/studio/file", True),
    ("/api/v1/agents/runs/p/r/log/stream", True),
    ("/api/v1/projects/p/videos", False),
    ("/api/v1/projects/p/studio/artifacts", False),
    ("/api/v1/agents/runs/p/r/log", False),
    ("/api/v1/auth/media-token", False),
    ("/api/v1/projects/p/studio/file/../../me", False),
])
def test_is_media_stream_path(path: str, expected: bool) -> None:
    assert is_media_stream_path(path) is expected


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
