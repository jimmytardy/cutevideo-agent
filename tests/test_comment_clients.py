"""Clients de commentaires YouTube / Instagram / TikTok (Zernio) : HTTP simulé, sans réseau ni base."""

from __future__ import annotations

import json
import sys
import types
import uuid
from datetime import datetime, UTC

import httpx
import pytest

from agent.core.database import Channel
from agent.skills.publisher import comments, credentials, tiktok_providers as tp
from agent.skills.publisher.comments import parse_platform_timestamp
from tests.test_instagram_publisher import FakeSession, _ctx


def _channel(config: dict | None = None, **kw) -> Channel:
    return Channel(
        id=uuid.uuid4(), user_id=uuid.uuid4(), slug="science-fun", name="Science",
        composio_user_id="science-fun", tiktok_enabled=True, config=config, **kw,
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-10-19T10:00:00Z", datetime(2026, 10, 19, 10, tzinfo=UTC)),
        ("2026-10-19T10:00:00+0000", datetime(2026, 10, 19, 10, tzinfo=UTC)),
        ("2026-10-19T12:00:00+02:00", datetime(2026, 10, 19, 10, tzinfo=UTC)),
        ("2026-10-19T10:00:00", datetime(2026, 10, 19, 10, tzinfo=UTC)),
        (1776592800, datetime(2026, 4, 19, 10, tzinfo=UTC)),
        ("1776592800000", datetime(2026, 4, 19, 10, tzinfo=UTC)),
        (1776592800000.0, datetime(2026, 4, 19, 10, tzinfo=UTC)),
        ("hier", None), ("", None), (None, None), (True, None),
    ],
)
def test_parse_platform_timestamp(raw, expected) -> None:
    assert parse_platform_timestamp(raw) == expected


def test_client_for_depends_on_the_tiktok_provider(monkeypatch) -> None:
    monkeypatch.setattr("agent.core.channel_config.load_agent_config", lambda: {"publishing": {}})
    assert comments.client_for(_channel(), "youtube").platform == "youtube"
    assert comments.client_for(_channel(), "instagram").platform == "instagram"
    assert comments.client_for(_channel({"tiktok": {"provider": "zernio"}}), "tiktok").platform == "tiktok"
    assert comments.client_for(_channel({"tiktok": {"provider": "postforme"}}), "tiktok") is None
    assert comments.client_for(_channel(), "tiktok") is None  # composio par défaut
    assert comments.client_for(_channel(), "facebook") is None


# ── YouTube ──────────────────────────────────────────────────────────────────


class _Call:
    """Imite les objets chaînés de googleapiclient : `youtube.x().y(**kw).execute()`."""

    def __init__(self, log: list, responses: dict) -> None:
        self.log, self.responses, self.name = log, responses, ""

    def __getattr__(self, name: str):
        def method(**kwargs):
            call = _Call(self.log, self.responses)
            call.name = f"{self.name}.{name}".strip(".")
            if kwargs:
                self.log.append((call.name, kwargs))
            return call
        return method

    def execute(self):
        return self.responses[self.name]


def _fake_youtube(monkeypatch, responses: dict) -> list:
    log: list = []
    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = lambda *a, **kw: _Call(log, responses)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "googleapiclient", types.ModuleType("googleapiclient"))
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)
    monkeypatch.setattr(comments, "build_youtube_credentials", lambda token: f"creds:{token}")

    async def token(channel):
        return "rt-1"

    monkeypatch.setattr(credentials, "youtube_refresh_token", token)
    return log


def _yt_comment(cid: str, author: str, text: str, replies_by: list[str] = ()) -> dict:
    return {
        "id": cid,
        "snippet": {"topLevelComment": {"id": cid, "snippet": {
            "textOriginal": text, "authorDisplayName": author.upper(), "publishedAt": "2026-10-19T10:00:00Z",
            "authorChannelId": {"value": author},
        }}},
        "replies": {"comments": [{"snippet": {"authorChannelId": {"value": r}}} for r in replies_by]},
    }


@pytest.mark.asyncio
async def test_youtube_lists_and_replies(monkeypatch) -> None:
    log = _fake_youtube(monkeypatch, {
        "commentThreads.list": {"items": [
            _yt_comment("c1", "UCfan", "Top !"),
            _yt_comment("c2", "UCme", "Merci à tous"),
            _yt_comment("c3", "UCfan2", "?", replies_by=["UCme"]),
        ]},
        "comments.insert": {"id": "r1"},
    })
    ch = _channel(youtube_channel_id="UCme")
    client = comments.YouTubeComments()
    got = await client.list_comments(ch, "vid1")
    assert [(c.platform_comment_id, c.author_name, c.is_owner, c.has_owner_reply) for c in got] == [
        ("c1", "UCFAN", False, False), ("c2", "UCME", True, False), ("c3", "UCFAN2", False, True),
    ]
    assert got[0].created_at == datetime(2026, 10, 19, 10, tzinfo=UTC)
    assert log[0] == ("commentThreads.list", {
        "part": "snippet,replies", "videoId": "vid1", "order": "time", "maxResults": 100, "textFormat": "plainText"})
    assert await client.reply(ch, "vid1", "c1", "Merci !") == "r1"
    assert log[-1] == ("comments.insert", {"part": "snippet", "body": {"snippet": {"parentId": "c1", "textOriginal": "Merci !"}}})


@pytest.mark.asyncio
async def test_youtube_resolves_the_owner_when_the_channel_id_is_missing(monkeypatch) -> None:
    log = _fake_youtube(monkeypatch, {
        "channels.list": {"items": [{"id": "UCme"}]},
        "commentThreads.list": {"items": [_yt_comment("c1", "UCme", "Épinglé")]},
    })
    got = await comments.YouTubeComments().list_comments(_channel(), "vid1")
    assert got[0].is_owner is True and log[0] == ("channels.list", {"part": "id", "mine": True})


@pytest.mark.asyncio
async def test_youtube_requires_a_token(monkeypatch) -> None:
    async def no_token(channel):
        return None

    monkeypatch.setattr(credentials, "youtube_refresh_token", no_token)
    with pytest.raises(RuntimeError, match="Token YouTube manquant"):
        await comments.YouTubeComments().list_comments(_channel(), "vid1")


# ── Instagram ────────────────────────────────────────────────────────────────


def _instagram_creds(monkeypatch, page_id: str | None = "page1") -> None:
    async def creds(channel):
        return credentials.InstagramCredentials("tok", page_id) if page_id else None

    monkeypatch.setattr(credentials, "instagram_credentials", creds)


@pytest.mark.asyncio
async def test_instagram_lists_and_replies(monkeypatch) -> None:
    _instagram_creds(monkeypatch)
    session = FakeSession([
        (200, {"data": [
            {"id": "c1", "text": "Génial", "username": "fan", "from": {"id": "u9", "username": "fan"},
             "timestamp": "2026-10-19T10:00:00+0000", "replies": {"data": [{"id": "r0", "from": {"id": "page1"}}]}},
            {"id": "c2", "text": "Merci", "username": "moi"},  # sans `from` : repli sur le profil connecté
            {"id": "c3", "text": "Hey", "from": {"id": "page1", "username": "moi"}},
        ]}),
        (200, {"id": "r1"}),
    ])
    monkeypatch.setattr(comments.aiohttp, "ClientSession", lambda **kw: _ctx(session))
    ch = _channel(instagram_profile={"username": "moi"})
    client = comments.InstagramComments()
    got = await client.list_comments(ch, "media1")
    assert [(c.platform_comment_id, c.author_name, c.is_owner, c.has_owner_reply) for c in got] == [
        ("c1", "fan", False, True), ("c2", "moi", True, False), ("c3", "moi", True, False),
    ]
    assert got[0].created_at == datetime(2026, 10, 19, 10, tzinfo=UTC)
    method, url, kwargs = session.calls[0]
    assert method == "GET" and url.endswith("/media1/comments")
    assert kwargs["params"]["fields"].startswith("id,text,username,from{id,username},timestamp,replies")
    assert kwargs["params"]["access_token"] == "tok"
    assert await client.reply(ch, "media1", "c1", "Merci !") == "r1"
    method, url, kwargs = session.calls[1]
    assert method == "POST" and url.endswith("/c1/replies") and kwargs["data"] == {"message": "Merci !", "access_token": "tok"}


@pytest.mark.asyncio
async def test_instagram_reply_refused_or_missing_credentials(monkeypatch) -> None:
    _instagram_creds(monkeypatch)
    session = FakeSession([(400, {"error": {"code": 10, "message": "(#10) Permission denied"}})])
    monkeypatch.setattr(comments.aiohttp, "ClientSession", lambda **kw: _ctx(session))
    with pytest.raises(RuntimeError, match="réponse au commentaire refusée"):
        await comments.InstagramComments().reply(_channel(), "media1", "c1", "Merci")
    _instagram_creds(monkeypatch, page_id=None)
    with pytest.raises(RuntimeError, match="Token Instagram"):
        await comments.InstagramComments().list_comments(_channel(), "media1")


# ── TikTok via Zernio ────────────────────────────────────────────────────────


@pytest.fixture
def zernio(monkeypatch) -> list[httpx.Request]:
    async def fake_key(channel: Channel, provider: str) -> str:
        return f"key-{provider}"

    monkeypatch.setattr(tp, "_api_key", fake_key)
    monkeypatch.setattr(tp, "RETRY_DELAYS_S", (0, 0))
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.method == "GET" and req.url.path == "/api/v1/inbox/comments/post9":
            return httpx.Response(200, json={"comments": [
                {"id": "t1", "message": "Trop bien", "createdTime": "2026-10-19T10:00:00Z",
                 "from": {"id": "f1", "name": "Fan", "isOwner": False}, "replies": [], "canReply": True},
                {"id": "t2", "message": "Merci !", "from": {"id": "me", "username": "sci", "isOwner": True}},
                {"id": "t3", "message": "?", "from": {"id": "f2"}, "replies": [{"from": {"isOwner": True}}]},
                {"id": "t4", "message": "fermé", "from": {"id": "f3"}, "canReply": False},
                "pas un objet",
            ]})
        if req.method == "POST" and req.url.path == "/api/v1/inbox/comments/post9":
            return httpx.Response(200, json={"success": True, "data": {"commentId": "r1", "isReply": True}})
        return httpx.Response(404)

    monkeypatch.setattr(tp, "_transport", httpx.MockTransport(handler))
    return seen


@pytest.mark.asyncio
async def test_tiktok_lists_and_replies_through_zernio(zernio) -> None:
    ch = _channel({"tiktok": {"provider": "zernio", "accounts": {"zernio": {"account_id": "acc1"}}}})
    client = comments.TikTokComments()
    got = await client.list_comments(ch, "post9")
    assert [(c.platform_comment_id, c.author_name, c.text, c.is_owner, c.has_owner_reply) for c in got] == [
        ("t1", "Fan", "Trop bien", False, False), ("t2", "sci", "Merci !", True, False), ("t3", "", "?", False, True),
    ]
    assert got[0].created_at == datetime(2026, 10, 19, 10, tzinfo=UTC)
    assert zernio[0].url.params["accountId"] == "acc1" and zernio[0].headers["authorization"] == "Bearer key-zernio"
    assert await client.reply(ch, "post9", "t1", "Merci Fan !") == "r1"
    body = json.loads(zernio[1].content)
    assert body == {"accountId": "acc1", "message": "Merci Fan !", "commentId": "t1"}
    assert zernio[1].headers["idempotency-key"] == "reply-t1"


@pytest.mark.asyncio
async def test_tiktok_requires_a_connected_zernio_account(zernio) -> None:
    ch = _channel({"tiktok": {"provider": "zernio"}})
    with pytest.raises(RuntimeError, match="non connecté"):
        await comments.TikTokComments().list_comments(ch, "post9")
    assert zernio == []
