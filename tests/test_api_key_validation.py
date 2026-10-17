"""État des clés API : classement des réponses des fournisseurs (réseau simulé, aucun appel réel)."""

from __future__ import annotations

import httpx
import pytest

from agent.core import api_key_validation as v


def _respond(status: int, body: object = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, dict):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=str(body or ""))

    return httpx.MockTransport(handler)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch):
    def install(status: int, body: object = None) -> None:
        monkeypatch.setattr(v, "_transport", _respond(status, body))

    return install


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "status", "body", "metadata", "expected"),
    [
        ("anthropic", 200, {"content": []}, None, "ok"),
        ("anthropic", 400, {"error": {"message": "Your credit balance is too low to access the API."}}, None,
         "no_credit"),
        ("anthropic", 401, {"error": {"type": "authentication_error"}}, None, "invalid"),
        ("anthropic", 429, {}, None, "quota"),
        ("anthropic", 529, {}, None, "unavailable"),
        ("fal", 422, {}, None, "ok"),
        ("fal", 403, {"detail": "User is locked. Reason: Exhausted balance."}, None, "no_credit"),
        ("fal", 401, {}, None, "invalid"),
        ("azure_speech", 200, "token", {"region": "francecentral"}, "ok"),
        ("azure_speech", 403, "Out of call volume quota.", {"region": "francecentral"}, "quota"),
        ("azure_speech", 401, "", {"region": "francecentral"}, "invalid"),
        ("postforme", 402, {}, None, "no_credit"),
        ("zernio", 403, {}, None, "invalid"),
        ("instagram", 400, {"error": {"code": 190, "error_subcode": 463, "message": "Session has expired"}},
         {"page_id": "1"}, "expired"),
        ("instagram", 400, {"error": {"code": 190, "message": "Invalid OAuth access token"}}, {"page_id": "1"},
         "invalid"),
        ("instagram", 400, {"error": {"code": 2500, "message": "An active access token must be used"}},
         {"page_id": "1"}, "invalid"),
        ("instagram", 400, {"error": {"code": 4, "message": "Application request limit reached"}},
         {"page_id": "1"}, "quota"),
    ],
)
async def test_check_api_key_classifies_provider_errors(transport, provider, status, body, metadata, expected) -> None:
    transport(status, body)
    health = await v.check_api_key(provider, "secret", metadata)
    assert health.status == expected
    assert expected == "ok" or health.detail


@pytest.mark.asyncio
async def test_youtube_revoked_token_is_expired(transport, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v.settings, "youtube_client_id", "id")
    monkeypatch.setattr(v.settings, "youtube_client_secret", "secret")
    transport(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
    assert (await v.check_api_key("youtube", "refresh")).status == "expired"


@pytest.mark.parametrize(
    ("code", "message", "expected"),
    [
        (429, "RESOURCE_EXHAUSTED: quota exceeded", "quota"),
        (400, "API key expired. Please renew the API key.", "expired"),
        (400, "API_KEY_INVALID", "invalid"),
    ],
)
def test_gemini_errors(code: int, message: str, expected: str) -> None:
    assert v._classify_gemini(code, message).status == expected


@pytest.mark.asyncio
async def test_network_error_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(v, "_transport", httpx.MockTransport(boom))
    assert (await v.check_api_key("fal", "secret")).status == "unavailable"


@pytest.mark.asyncio
async def test_anthropic_subscription_token_is_refused() -> None:
    with pytest.raises(v.ApiKeyValidationError, match="sk-ant-api"):
        await v.validate_api_key("anthropic", "sk-ant-oat01-abcdef")


@pytest.mark.asyncio
async def test_instagram_requires_page_id() -> None:
    with pytest.raises(v.ApiKeyValidationError, match="page_id"):
        await v.validate_api_key("instagram", "token", {})


@pytest.mark.asyncio
async def test_saving_a_key_without_credit_is_allowed(transport) -> None:
    """Seules les clés invalides ou expirées bloquent l'enregistrement (crédit épuisé : averti, pas refusé)."""
    transport(400, {"error": {"message": "Your credit balance is too low"}})
    await v.validate_api_key("anthropic", "sk-ant-api03-x")


@pytest.mark.asyncio
async def test_instagram_check_targets_configured_graph_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSTAGRAM_GRAPH_API_VERSION", "v99.0")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "1"})

    monkeypatch.setattr(v, "_transport", httpx.MockTransport(handler))
    assert (await v.check_api_key("instagram", "tok", {"page_id": "1"})).status == "ok"
    assert seen[0].url.host == "graph.facebook.com" and seen[0].url.path == "/v99.0/me"
    assert seen[0].url.params["access_token"] == "tok"
