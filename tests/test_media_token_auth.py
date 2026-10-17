"""Jeton média court : seul jeton accepté en `?access_token=`, et seulement sur les routes de flux (middleware)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request

from agent.core.auth import create_access_token, create_media_token
from api import main as api_main
from api.main import app, authenticate_api_requests
from api.middleware_auth import get_request_user_id, is_media_stream_path

# Routes réelles servies à des balises média / EventSource : chacune doit être reconnue par MEDIA_STREAM_PATH.
STREAM_ROUTES = (
    "/api/v1/projects/{project_id}/videos/{video_id}/stream",
    "/api/v1/projects/{project_id}/thumbnails/{index}/stream",
    "/api/v1/projects/{project_id}/studio/file",
    "/api/v1/agents/runs/{project_id}/{run_id}/log/stream",
)


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _route_paths(router) -> set[str]:
    """Chemins de toutes les routes, y compris celles des routeurs inclus (FastAPI ≥ 0.140 les enveloppe dans
    un `_IncludedRouter` qui expose le routeur d'origine)."""
    paths: set[str] = set()
    for route in router.routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            paths |= _route_paths(inner)
        elif hasattr(route, "path"):
            paths.add(route.path)
    return paths


def test_every_stream_route_exists_and_is_a_media_stream_path() -> None:
    paths = _route_paths(app)
    for template in STREAM_ROUTES:
        assert template in paths, template
        concrete = template.format(project_id=uuid.uuid4(), video_id=uuid.uuid4(), index=0, run_id=uuid.uuid4())
        assert is_media_stream_path(concrete), concrete


@pytest.mark.asyncio
async def test_media_token_in_query_authenticates_stream_routes(monkeypatch) -> None:
    """Chemin positif : jeton média en query → middleware → utilisateur posé sur la requête."""
    user_id = uuid.uuid4()

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def execute(self, _query):
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=user_id))

    monkeypatch.setattr(api_main, "AsyncSessionFactory", _Session)
    test_app = FastAPI()
    test_app.middleware("http")(authenticate_api_requests)

    @test_app.get("/api/v1/projects/{project_id}/studio/file")
    async def who(request: Request) -> dict:
        return {"user": str(get_request_user_id(request))}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as c:
        resp = await c.get("/api/v1/projects/p/studio/file", params={"access_token": create_media_token(user_id)})
    assert resp.status_code == 200 and resp.json() == {"user": str(user_id)}


@pytest.mark.asyncio
async def test_session_jwt_in_query_is_refused_even_on_stream_routes(client: httpx.AsyncClient) -> None:
    token = create_access_token(uuid.uuid4())
    async with client:
        resp = await client.get("/api/v1/projects/p/studio/file", params={"path": "voice.wav", "access_token": token})
    assert resp.status_code == 401 and resp.json()["detail"] == "Token invalide"


@pytest.mark.asyncio
async def test_media_token_in_authorization_header_is_refused(client: httpx.AsyncClient) -> None:
    token = create_media_token(uuid.uuid4())
    async with client:
        resp = await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401 and resp.json()["detail"] == "Token invalide"


@pytest.mark.asyncio
async def test_media_token_in_query_outside_stream_routes_is_ignored(client: httpx.AsyncClient) -> None:
    token = create_media_token(uuid.uuid4())
    async with client:
        resp = await client.get("/api/v1/projects", params={"access_token": token})
    assert resp.status_code == 401 and resp.json()["detail"] == "Authentification requise"


@pytest.mark.asyncio
async def test_media_token_route_requires_a_session(client: httpx.AsyncClient) -> None:
    async with client:
        resp = await client.post("/api/v1/auth/media-token")
    assert resp.status_code == 401
