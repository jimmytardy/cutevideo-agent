"""Publication TikTok via Post for Me / Zernio (HTTP simulé, sans réseau ni base)."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from agent.core.api_keys import ALLOWED_PROVIDERS, ApiKeyNotConfiguredError
from agent.core.database import Channel
from agent.skills.publisher import executor, tiktok_providers as tp

_REAL_API_KEY = tp._api_key


def _channel(config: dict | None = None, **kw) -> Channel:
    return Channel(
        id=uuid.uuid4(), user_id=uuid.uuid4(), slug="science-fun", name="Science",
        composio_user_id="science-fun", tiktok_enabled=True, config=config, **kw,
    )


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    async def fake_key(channel: Channel, provider: str) -> str:
        return f"key-{provider}"

    monkeypatch.setattr(tp, "_api_key", fake_key)
    monkeypatch.setattr(tp, "POLL_INTERVALS_S", (0, 0, 0))
    monkeypatch.setattr(tp, "RETRY_DELAYS_S", (0, 0))
    return []


def _mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(tp, "_transport", httpx.MockTransport(wrapped))
    return seen


def test_new_key_providers_are_allowed() -> None:
    assert {"postforme", "zernio"} <= ALLOWED_PROVIDERS


def test_provider_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.core.channel_config.load_agent_config", lambda: {"publishing": {}})
    assert tp.provider_name(_channel()) == "composio"
    monkeypatch.setattr(
        "agent.core.channel_config.load_agent_config", lambda: {"publishing": {"tiktok_provider": "zernio"}}
    )
    assert tp.provider_name(_channel()) == "zernio"
    assert tp.provider_name(_channel({"tiktok": {"provider": "postforme"}})) == "postforme"
    assert tp.provider_name(_channel({"tiktok": {"provider": "bidon"}})) == "composio"


def test_connected_depends_on_provider_account() -> None:
    ch = _channel({"tiktok": {"provider": "postforme", "accounts": {"zernio": {"account_id": "z1"}}}})
    assert not executor.channel_supports_platform(ch, "tiktok")
    ch.config = tp.with_provider_account(ch, "postforme", {"account_id": "spc_1", "username": "sci"})
    assert executor.channel_supports_platform(ch, "tiktok")
    assert tp.provider_account(ch, "zernio") == {"account_id": "z1"}  # l'autre compte est conservé


def test_caption_has_hashtags_and_is_capped() -> None:
    assert tp.build_caption("Titre", ["#shorts", "science"]) == "Titre\n\n#shorts #science"
    assert len(tp.build_caption("x" * 3000, [])) == tp.CAPTION_MAX


@pytest.mark.asyncio
async def test_postforme_publish_payload_and_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/v1/social-posts":
            return httpx.Response(200, json={"id": "sp_1", "status": "processing"})
        if req.url.path == "/v1/social-post-results":
            return httpx.Response(200, json={"data": [
                {"success": True, "platform_data": {"url": "https://tiktok.com/@sci/video/1"}}]})
        return httpx.Response(404)

    seen = _mock(monkeypatch, handler)
    ch = _channel({"tiktok": {"provider": "postforme", "accounts": {"postforme": {"account_id": "spc_1"}}}})
    post_id, url = await tp.PostForMePublisher().publish(
        ch, video_url="https://s3/v.mp4", caption="Cap", title="Titre", privacy="SELF_ONLY", external_id="pub-1",
    )
    assert (post_id, url) == ("sp_1", "https://tiktok.com/@sci/video/1")
    body = json.loads(seen[0].content)
    assert seen[0].headers["authorization"] == "Bearer key-postforme"
    assert body["social_accounts"] == ["spc_1"] and body["external_id"] == "pub-1"
    assert body["media"] == [{"url": "https://s3/v.mp4"}]
    cfg = body["platform_configurations"]["tiktok"]
    assert cfg["privacy_status"] == "private" and cfg["is_ai_generated"] is True
    assert seen[1].url.params["post_id"] == "sp_1"


@pytest.mark.asyncio
async def test_postforme_failure_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, text="busy")  # retenté
            return httpx.Response(200, json={"id": "sp_2"})
        return httpx.Response(200, json={"data": [{"success": False, "error": {"message": "video too short"}}]})

    _mock(monkeypatch, handler)
    ch = _channel({"tiktok": {"accounts": {"postforme": {"account_id": "spc_1"}}}})
    with pytest.raises(RuntimeError, match="video too short"):
        await tp.PostForMePublisher().publish(
            ch, video_url="u", caption="c", title="t", privacy="PUBLIC_TO_EVERYONE", external_id="p")
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_postforme_connect_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/social-accounts/auth-url":
            body = json.loads(req.content)
            assert body["platform"] == "tiktok" and body["redirect_url_override"] == "https://app/back"
            return httpx.Response(200, json={"url": "https://tiktok/auth", "platform": "tiktok"})
        if req.url.path == "/v1/social-accounts":
            assert req.url.params["platform"] == "tiktok"
            return httpx.Response(200, json={"data": [{"id": "spc_9", "username": "sci"}]})
        return httpx.Response(404)

    _mock(monkeypatch, handler)
    ch = _channel()
    pub = tp.PostForMePublisher()
    assert (await pub.start_connect(ch, "https://app/back"))["redirect_url"] == "https://tiktok/auth"
    assert await pub.finish_connect(ch, {}, {}) == {"account_id": "spc_9", "username": "sci"}


@pytest.mark.asyncio
async def test_zernio_publish_payload_and_draft_for_non_public(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/api/v1/posts":
            return httpx.Response(201, json={"post": {"_id": "p1", "status": "publishing"}})
        if req.url.path == "/api/v1/posts/p1":
            return httpx.Response(200, json={"post": {"_id": "p1", "status": "published", "platforms": [
                {"platform": "tiktok", "platformPostUrl": "https://tiktok.com/v/1"}]}})
        return httpx.Response(404)

    seen = _mock(monkeypatch, handler)
    ch = _channel({"tiktok": {"provider": "zernio", "accounts": {"zernio": {"account_id": "acc1"}}}})
    pub = tp.ZernioPublisher()
    assert await pub.publish(ch, video_url="https://s3/v.mp4", caption="Cap", title="T",
                             privacy="PUBLIC_TO_EVERYONE", external_id="pub-7") == ("p1", "https://tiktok.com/v/1")
    body = json.loads(seen[0].content)
    assert seen[0].headers["x-request-id"] == "pub-7"
    assert body["platforms"] == [{"platform": "tiktok", "accountId": "acc1"}] and body["publishNow"] is True
    s = body["tiktokSettings"]
    assert s["content_preview_confirmed"] and s["express_consent_given"] and s["video_made_with_ai"]
    assert "draft" not in s

    seen.clear()
    await pub.publish(ch, video_url="u", caption="c", title="t", privacy="SELF_ONLY", external_id="pub-8")
    assert json.loads(seen[0].content)["tiktokSettings"]["draft"] is True


@pytest.mark.asyncio
async def test_zernio_failed_post_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(201, json={"post": {"_id": "p2"}})
        return httpx.Response(200, json={"post": {"status": "failed", "error": "bad"}})

    _mock(monkeypatch, handler)
    ch = _channel({"tiktok": {"accounts": {"zernio": {"account_id": "acc1"}}}})
    with pytest.raises(RuntimeError, match="échouée"):
        await tp.ZernioPublisher().publish(ch, video_url="u", caption="c", title="t",
                                           privacy="PUBLIC_TO_EVERYONE", external_id="x")


@pytest.mark.asyncio
async def test_zernio_connect_creates_profile_and_reads_account(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/profiles":
            assert json.loads(req.content) == {"name": "science-fun"}
            return httpx.Response(201, json={"profile": {"_id": "prof1"}})
        if req.url.path == "/api/v1/connect/tiktok":
            assert req.url.params["profileId"] == "prof1"
            return httpx.Response(200, json={"authUrl": "https://tiktok/auth"})
        if req.url.path == "/api/v1/accounts":
            return httpx.Response(200, json={"accounts": [
                {"_id": "a_x", "platform": "youtube", "profileId": "prof1"},
                {"_id": "a_tt", "platform": "tiktok", "profileId": {"_id": "prof1"}, "username": "sci"}]})
        return httpx.Response(404)

    _mock(monkeypatch, handler)
    ch = _channel()
    pub = tp.ZernioPublisher()
    started = await pub.start_connect(ch, "https://app/back")
    assert started == {"redirect_url": "https://tiktok/auth", "extra": {"profile_id": "prof1"}}
    # Paramètres de retour présents → pas d'appel ; absents → lecture des comptes du profil.
    assert (await pub.finish_connect(ch, {"accountId": "a1", "username": "u"}, started["extra"]))["account_id"] == "a1"
    acc = await pub.finish_connect(ch, {}, started["extra"])
    assert acc == {"account_id": "a_tt", "username": "sci", "profile_id": "prof1"}


@pytest.mark.asyncio
async def test_missing_key_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.core import api_keys

    async def no_key(*args, **kwargs):
        return api_keys.ApiKeyContext(user_id=None, provider="postforme", key=None, source="none", tier="free")

    monkeypatch.setattr(api_keys, "fetch_api_key", no_key)
    with pytest.raises(ApiKeyNotConfiguredError, match="Clés API"):
        await _REAL_API_KEY(_channel(), "postforme")
