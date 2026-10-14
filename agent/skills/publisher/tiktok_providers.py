"""Publication TikTok par fournisseur : Composio, Post for Me ou Zernio.

Le fournisseur se choisit par chaîne (`Channel.config["tiktok"]["provider"]`), sinon
`data/agent_config.json → publishing.tiktok_provider` (défaut `composio`). Les clés API de
Post for Me / Zernio sont celles de l'utilisateur (Compte → Clés API, table `user_api_keys`).

Post for Me et Zernio publient via **leur** appli TikTok auditée : les vidéos peuvent être
publiques sans faire auditer une appli à nous. Les comptes connectés sont rangés par fournisseur
dans `Channel.config["tiktok"]["accounts"][<fournisseur>]` (changer de fournisseur ne perd rien).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

import httpx

from agent.core.database import Channel
from agent.skills.publisher import composio_client

logger = logging.getLogger(__name__)

PROVIDERS = ("composio", "postforme", "zernio")
POLL_INTERVALS_S: tuple[float, ...] = (5, 10, 20, 30, 60, 60, 60)
RETRY_DELAYS_S: tuple[float, ...] = (1, 3, 8)
HTTP_TIMEOUT_S = 30.0
CAPTION_MAX = 2200

# Remplaçable dans les tests (httpx.MockTransport).
_transport: httpx.AsyncBaseTransport | None = None

# Confidentialité : valeurs historiques (onboarding, Composio) → Post for Me.
_POSTFORME_PRIVACY = {
    "PUBLIC_TO_EVERYONE": "public",
    "MUTUAL_FOLLOW_FRIENDS": "friends",
    "FOLLOWER_OF_CREATOR": "followers",
    "SELF_ONLY": "private",
}


class TikTokPublisher(Protocol):
    name: str

    def is_connected(self, channel: Channel) -> bool: ...

    async def start_connect(self, channel: Channel, redirect_url: str) -> dict[str, Any]:
        """Renvoie `{"redirect_url": …}` (+ `extra` à remettre à `finish_connect`)."""

    async def finish_connect(
        self, channel: Channel, params: dict[str, str], extra: dict[str, Any]
    ) -> dict[str, Any]:
        """Renvoie le compte connecté (`account_id`, `username`, …) à enregistrer."""

    async def publish(
        self,
        channel: Channel,
        *,
        video_url: str,
        caption: str,
        title: str,
        privacy: str,
        external_id: str,
    ) -> tuple[str, str | None]:
        """Publie et attend le résultat. Renvoie (id du post, URL publique ou None)."""


# ── Réglages de la chaîne ────────────────────────────────────────────────────


def tiktok_settings(channel: Channel) -> dict[str, Any]:
    cfg = (channel.config or {}).get("tiktok")
    return dict(cfg) if isinstance(cfg, dict) else {}


def provider_account(channel: Channel, provider: str) -> dict[str, Any]:
    accounts = tiktok_settings(channel).get("accounts") or {}
    acc = accounts.get(provider) if isinstance(accounts, dict) else None
    return dict(acc) if isinstance(acc, dict) else {}


def with_provider_account(channel: Channel, provider: str, account: dict[str, Any]) -> dict[str, Any]:
    """Nouveau `Channel.config` avec le compte du fournisseur enregistré."""
    config = dict(channel.config or {})
    tiktok = tiktok_settings(channel)
    accounts = dict(tiktok.get("accounts") or {})
    accounts[provider] = {**accounts.get(provider, {}), **account}
    tiktok["accounts"] = accounts
    config["tiktok"] = tiktok
    return config


def provider_name(channel: Channel) -> str:
    name = str(tiktok_settings(channel).get("provider") or "").strip().lower()
    if not name:
        from agent.core.channel_config import load_agent_config

        name = str(load_agent_config().get("publishing", {}).get("tiktok_provider") or "composio").lower()
    return name if name in PROVIDERS else "composio"


def get_tiktok_publisher(channel: Channel) -> TikTokPublisher:
    return _PUBLISHERS[provider_name(channel)]


def build_caption(title: str, hashtags: list[str] | None) -> str:
    tags = " ".join(t if t.startswith("#") else f"#{t}" for t in (hashtags or []) if t)
    caption = f"{title}\n\n{tags}".strip() if tags else title.strip()
    return caption[:CAPTION_MAX]


# ── HTTP commun ──────────────────────────────────────────────────────────────


async def _api_key(channel: Channel, provider: str) -> str:
    from agent.core.api_keys import ApiKeyNotConfiguredError, fetch_api_key

    ctx = await fetch_api_key(channel.user_id, provider, purpose="tiktok_publish")  # type: ignore[arg-type]
    if not ctx.key:
        raise ApiKeyNotConfiguredError(
            f"Clé {provider} non configurée pour le propriétaire de la chaîne {channel.slug} "
            "(Compte → Clés API)."
        )
    return ctx.key


async def _request(
    base_url: str,
    key: str,
    method: str,
    path: str,
    *,
    label: str,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Appel JSON avec nouvelles tentatives sur 429 / 5xx / erreur réseau."""
    hdrs = {"Authorization": f"Bearer {key}", **(headers or {})}
    last_error = ""
    for delay in (0.0, *RETRY_DELAYS_S):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(
                base_url=base_url, timeout=HTTP_TIMEOUT_S, transport=_transport
            ) as client:
                resp = await client.request(method, path, headers=hdrs, **kwargs)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = f"HTTP {resp.status_code} {resp.text[:300]}"
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"{label} {method} {path} → HTTP {resp.status_code} : {resp.text[:500]}")
        return resp.json() if resp.content else {}
    raise RuntimeError(f"{label} {method} {path} indisponible après {len(RETRY_DELAYS_S) + 1} essais : {last_error}")


# ── Composio (comportement historique) ──────────────────────────────────────


class ComposioPublisher:
    name = "composio"

    def is_connected(self, channel: Channel) -> bool:
        return composio_client.tiktok_is_connected(channel)

    async def start_connect(self, channel: Channel, redirect_url: str) -> dict[str, Any]:
        oauth = await composio_client.initiate_tiktok_oauth(channel)
        return {"redirect_url": oauth["redirect_url"], "extra": {"connection_id": oauth["connection_id"]}}

    async def finish_connect(
        self, channel: Channel, params: dict[str, str], extra: dict[str, Any]
    ) -> dict[str, Any]:
        connection_id = extra.get("connection_id") or params.get("connection_id")
        if not connection_id:
            raise RuntimeError("connection_id Composio manquant")
        account_id = await composio_client.wait_for_tiktok_connection(str(connection_id), channel)
        return {"account_id": account_id}

    async def publish(
        self,
        channel: Channel,
        *,
        video_url: str,
        caption: str,
        title: str,
        privacy: str,
        external_id: str,
    ) -> tuple[str, str | None]:
        publish_id = await composio_client.publish_tiktok_video(
            channel=channel, video_url=video_url, caption=caption, privacy_level=privacy
        )
        return publish_id, None


# ── Post for Me ─────────────────────────────────────────────────────────────


class PostForMePublisher:
    name = "postforme"
    base_url = "https://api.postforme.dev"
    label = "Post for Me"

    def is_connected(self, channel: Channel) -> bool:
        return bool(channel.tiktok_enabled and provider_account(channel, self.name).get("account_id"))

    async def _call(self, key: str, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return await _request(self.base_url, key, method, path, label=self.label, **kwargs)

    async def start_connect(self, channel: Channel, redirect_url: str) -> dict[str, Any]:
        key = await _api_key(channel, self.name)
        data = await self._call(key, "POST", "/v1/social-accounts/auth-url", json={
            "platform": "tiktok",
            "external_id": str(channel.id),
            "redirect_url_override": redirect_url,
        })
        if not data.get("url"):
            raise RuntimeError(f"{self.label} : URL d'autorisation absente ({data})")
        return {"redirect_url": data["url"], "extra": {}}

    async def finish_connect(
        self, channel: Channel, params: dict[str, str], extra: dict[str, Any]
    ) -> dict[str, Any]:
        key = await _api_key(channel, self.name)
        data = await self._call(key, "GET", "/v1/social-accounts", params={
            "external_id": str(channel.id), "platform": "tiktok", "status": "connected",
        })
        accounts = data.get("data") or []
        if not accounts:
            raise RuntimeError(f"{self.label} : aucun compte TikTok connecté pour cette chaîne")
        acc = accounts[-1]
        return {"account_id": str(acc["id"]), "username": acc.get("username")}

    async def publish(
        self,
        channel: Channel,
        *,
        video_url: str,
        caption: str,
        title: str,
        privacy: str,
        external_id: str,
    ) -> tuple[str, str | None]:
        account_id = provider_account(channel, self.name).get("account_id")
        if not account_id:
            raise RuntimeError(f"TikTok ({self.label}) non connecté pour la chaîne {channel.slug}")
        key = await _api_key(channel, self.name)
        post = await self._call(key, "POST", "/v1/social-posts", json={
            "caption": caption,
            "media": [{"url": video_url}],
            "social_accounts": [account_id],
            "external_id": external_id,
            "platform_configurations": {
                "tiktok": {
                    "title": title[:90],
                    "privacy_status": _POSTFORME_PRIVACY.get(privacy, "public"),
                    "allow_comment": True,
                    "allow_duet": True,
                    "allow_stitch": True,
                    "is_ai_generated": True,
                }
            },
        })
        post_id = str(post.get("id") or "")
        if not post_id:
            raise RuntimeError(f"{self.label} : création du post sans id ({post})")
        return post_id, await self._wait_result(key, post_id)

    async def _wait_result(self, key: str, post_id: str) -> str | None:
        for interval in POLL_INTERVALS_S:
            await asyncio.sleep(interval)
            data = await self._call(key, "GET", "/v1/social-post-results", params={"post_id": post_id})
            for result in data.get("data") or []:
                if result.get("success"):
                    return (result.get("platform_data") or {}).get("url")
                if result.get("error"):
                    raise RuntimeError(f"Publication TikTok ({self.label}) échouée : {result['error']}")
        raise RuntimeError(f"{self.label} : pas de résultat pour le post {post_id} (délai dépassé)")


# ── Zernio ──────────────────────────────────────────────────────────────────


class ZernioPublisher:
    name = "zernio"
    base_url = "https://zernio.com/api/v1"
    label = "Zernio"

    def is_connected(self, channel: Channel) -> bool:
        return bool(channel.tiktok_enabled and provider_account(channel, self.name).get("account_id"))

    async def _call(self, key: str, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return await _request(self.base_url, key, method, path, label=self.label, **kwargs)

    async def _profile_id(self, key: str, channel: Channel) -> str:
        existing = provider_account(channel, self.name).get("profile_id")
        if existing:
            return str(existing)
        data = await self._call(key, "POST", "/profiles", json={"name": channel.slug})
        profile = data.get("profile") or data
        profile_id = profile.get("_id") or profile.get("id")
        if not profile_id:
            raise RuntimeError(f"{self.label} : création du profil sans id ({data})")
        return str(profile_id)

    async def start_connect(self, channel: Channel, redirect_url: str) -> dict[str, Any]:
        key = await _api_key(channel, self.name)
        profile_id = await self._profile_id(key, channel)
        data = await self._call(key, "GET", "/connect/tiktok", params={
            "profileId": profile_id, "redirect_url": redirect_url,
        })
        auth_url = data.get("authUrl") or data.get("url")
        if not auth_url:
            raise RuntimeError(f"{self.label} : URL d'autorisation absente ({data})")
        return {"redirect_url": auth_url, "extra": {"profile_id": profile_id}}

    async def finish_connect(
        self, channel: Channel, params: dict[str, str], extra: dict[str, Any]
    ) -> dict[str, Any]:
        profile_id = str(extra.get("profile_id") or params.get("profileId") or "")
        if params.get("accountId"):
            return {"account_id": params["accountId"], "username": params.get("username"), "profile_id": profile_id}
        key = await _api_key(channel, self.name)
        data = await self._call(key, "GET", "/accounts", params={"profileId": profile_id} if profile_id else None)
        accounts = [
            a for a in data.get("accounts") or []
            if a.get("platform") == "tiktok"
            and (not profile_id or str(_ref_id(a.get("profileId"))) in ("", profile_id))
        ]
        if not accounts:
            raise RuntimeError(f"{self.label} : aucun compte TikTok connecté sur ce profil")
        acc = accounts[-1]
        return {"account_id": str(acc["_id"]), "username": acc.get("username"), "profile_id": profile_id}

    async def publish(
        self,
        channel: Channel,
        *,
        video_url: str,
        caption: str,
        title: str,
        privacy: str,
        external_id: str,
    ) -> tuple[str, str | None]:
        account_id = provider_account(channel, self.name).get("account_id")
        if not account_id:
            raise RuntimeError(f"TikTok ({self.label}) non connecté pour la chaîne {channel.slug}")
        key = await _api_key(channel, self.name)
        body: dict[str, Any] = {
            "content": caption,
            "mediaItems": [{"type": "video", "url": video_url}],
            "platforms": [{"platform": "tiktok", "accountId": account_id}],
            "tiktokSettings": {
                "privacy_level": privacy or "PUBLIC_TO_EVERYONE",
                "allow_comment": True,
                "allow_duet": True,
                "allow_stitch": True,
                "content_preview_confirmed": True,
                "express_consent_given": True,
                "video_made_with_ai": True,
            },
            "publishNow": True,
        }
        # Comptes « TikTok Business » : publication directe uniquement en public, sinon brouillon.
        if body["tiktokSettings"]["privacy_level"] != "PUBLIC_TO_EVERYONE":
            body["tiktokSettings"]["draft"] = True
        data = await self._call(key, "POST", "/posts", json=body, headers={"x-request-id": external_id})
        post = data.get("post") or data
        post_id = str(post.get("_id") or post.get("id") or "")
        if not post_id:
            raise RuntimeError(f"{self.label} : création du post sans id ({data})")
        return post_id, await self._wait_result(key, post_id)

    async def _wait_result(self, key: str, post_id: str) -> str | None:
        for interval in POLL_INTERVALS_S:
            await asyncio.sleep(interval)
            data = await self._call(key, "GET", f"/posts/{post_id}")
            post = data.get("post") or data
            status = str(post.get("status") or "").lower()
            if status == "published":
                for p in post.get("platforms") or []:
                    if p.get("platform") == "tiktok":
                        return p.get("platformPostUrl")
                return None
            if status in ("failed", "partial"):
                raise RuntimeError(f"Publication TikTok ({self.label}) échouée : {post}")
        raise RuntimeError(f"{self.label} : post {post_id} toujours en cours (délai dépassé)")


def _ref_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("_id") or value.get("id") or "")
    return str(value or "")


_PUBLISHERS: dict[str, TikTokPublisher] = {
    "composio": ComposioPublisher(),
    "postforme": PostForMePublisher(),
    "zernio": ZernioPublisher(),
}
