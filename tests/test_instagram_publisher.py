"""Graph API Instagram : une seule version, surchargeable par INSTAGRAM_GRAPH_API_VERSION (agent/skills/publisher/graph_api.py)."""

from __future__ import annotations

import json

import aiohttp
import pytest

from agent.skills.publisher import graph_api, instagram


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



class _FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status, self._body = status, body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class FakeSession:
    """Remplace aiohttp.ClientSession : une liste de (statut, corps) servis dans l'ordre, appels enregistrés."""

    def __init__(self, replies: list[tuple[int, object]]) -> None:
        self.replies, self.calls = list(replies), []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.replies:
            raise aiohttp.ClientConnectionError("plus de réponse prévue")
        status, body = self.replies.pop(0)
        if isinstance(body, Exception):
            raise body
        return _FakeResponse(status, body if isinstance(body, str) else json.dumps(body))


async def _no_sleep(_s: float) -> None:
    return None


async def _upload(session: FakeSession, monkeypatch, **kwargs) -> str | None:
    monkeypatch.setattr(instagram, "wait_until_container_ready",
                        lambda s, c, t, **kw: instagram_wait(s, c, t, sleep=_no_sleep, **kw))
    return await instagram.upload_reel(None, "Titre", ["shorts", "#animaux"], "https://cdn/x.mp4", "page1", "tok")


instagram_wait = instagram.wait_until_container_ready


@pytest.mark.asyncio
async def test_upload_reel_publishes_only_once_the_container_is_finished(monkeypatch) -> None:
    session = FakeSession([
        (200, {"id": "container-1"}),
        (200, {"status_code": "IN_PROGRESS"}),
        (503, "<html>bad gateway</html>"),            # transitoire : on continue d'attendre
        (400, {"error": {"code": 4, "message": "Application request limit reached"}}),  # limite de débit : idem
        (200, {"status_code": "FINISHED"}),
        (200, {"id": "media-9"}),
    ])
    monkeypatch.setattr(instagram.aiohttp, "ClientSession", lambda **kw: _ctx(session))
    assert await _upload(session, monkeypatch) == "media-9"
    methods = [(m, u.rsplit("/", 1)[-1]) for m, u, _ in session.calls]
    assert methods == [("POST", "media"), ("GET", "container-1"), ("GET", "container-1"), ("GET", "container-1"),
                       ("GET", "container-1"), ("POST", "media_publish")]
    assert session.calls[0][2]["data"]["caption"] == "Titre\n\n#shorts #animaux"
    assert session.calls[-1][2]["data"]["creation_id"] == "container-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["ERROR", "EXPIRED"])
async def test_upload_reel_fails_clearly_when_meta_rejects_the_container(monkeypatch, code: str) -> None:
    session = FakeSession([(200, {"id": "container-1"}), (200, {"status_code": code, "status": "Codec not supported"})])
    monkeypatch.setattr(instagram.aiohttp, "ClientSession", lambda **kw: _ctx(session))
    with pytest.raises(RuntimeError, match=f"instagram_container_{code.lower()} : Codec not supported"):
        await _upload(session, monkeypatch)
    assert [m for m, _, _ in session.calls].count("POST") == 1  # jamais de media_publish sur un conteneur refusé


@pytest.mark.asyncio
async def test_wait_stops_immediately_on_a_fatal_graph_error(monkeypatch) -> None:
    session = FakeSession([(400, {"error": {"code": 190, "error_subcode": 463, "message": "Session has expired"}})])
    with pytest.raises(RuntimeError, match="instagram_graph_error : HTTP 400, code 190/463"):
        await instagram.wait_until_container_ready(session, "c1", "tok", sleep=_no_sleep)
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_wait_times_out_after_transient_errors(monkeypatch) -> None:
    session = FakeSession([(200, {"status_code": "IN_PROGRESS"}), (502, "<html>"), (200, {"status_code": "IN_PROGRESS"})])
    with pytest.raises(RuntimeError, match="instagram_container_timeout : traitement toujours IN_PROGRESS"):
        await instagram.wait_until_container_ready(session, "c1", "tok", timeout_s=0, sleep=_no_sleep)


@pytest.mark.asyncio
async def test_graph_post_logs_and_returns_none_without_id(caplog) -> None:
    session = FakeSession([(200, {"success": True}), (502, "<html>oops</html>")])
    with caplog.at_level("WARNING"):
        assert await instagram._graph_post(session, "https://graph.facebook.com/v26.0/p/media", {}, step="création") is None
        assert await instagram._graph_post(session, "https://graph.facebook.com/v26.0/p/media", {}, step="création") is None
    assert "sans id" in caplog.text and "réponse non JSON (HTTP 502)" in caplog.text


class _ctx:
    """Contexte async minimal pour remplacer `async with aiohttp.ClientSession(...)`."""

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *exc) -> None:
        return None
