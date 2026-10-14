from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Literal

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.auth import create_oauth_state, decode_oauth_state
from agent.core.channel_brand import ChannelBrandKit, YouTubeBrand
from agent.core.config import settings
from agent.core.database import Channel, User, get_db
from agent.core.subscription import QuotaExceededError, check_can_create_channel
from agent.skills.publisher import youtube_branding
from agent.skills.publisher.credentials import youtube_refresh_token
from api.authorization import get_user_channel
from api.deps import get_current_user
from api.models import (
    ChannelResponse,
    OnboardingDraftRequest,
    OnboardingInstagramRequest,
    OnboardingTikTokRequest,
    OnboardingYoutubeRequest,
    YouTubeChannelItem,
    YouTubeOAuthUrlResponse,
)

logger = logging.getLogger(__name__)
# Référence forte : sans elle, le GC peut collecter une tâche en cours.
_background_tasks: set[asyncio.Task[bool]] = set()

router = APIRouter(prefix="/api/v1/channels", tags=["channel-onboarding"])

YOUTUBE_OAUTH_DONE_PATH = "/oauth/youtube/done"


def _youtube_oauth_done_url(*, channel_id: str | None = None, error: str | None = None) -> str:
    base = settings.api_base_url.rstrip("/")
    params: dict[str, str] = {}
    if channel_id:
        params["channel_id"] = channel_id
    if error:
        params["error"] = error
    else:
        params["status"] = "ok"
    return f"{base}{YOUTUBE_OAUTH_DONE_PATH}?{urlencode(params)}"


def _config_from_brand_kit(brand_kit: dict[str, Any]) -> dict[str, Any]:
    return {
        "publishing": {"default_tags": brand_kit.get("default_tags", [])},
        "media_source_priority": brand_kit.get("media_source_priority"),
    }


ONBOARDING_SKIP_NEXT: dict[str, str] = {
    "youtube": "tiktok",
    "tiktok": "instagram",
    "instagram": "complete",
}


def _disable_platform_in_config(channel: Channel, platform: str) -> None:
    cfg = dict(channel.config or {})
    pub = dict(cfg.get("publishing") or {})
    enabled = list(pub.get("enabled_platforms") or ["youtube", "tiktok", "instagram"])
    pub["enabled_platforms"] = [p for p in enabled if p != platform]
    cfg["publishing"] = pub
    channel.config = cfg
    if platform == "tiktok":
        channel.tiktok_enabled = False


@router.post("/onboarding/draft", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_onboarding_draft(
    body: OnboardingDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    try:
        await check_can_create_channel(db, current_user)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    brand_kit = body.brand_kit
    slug = str(brand_kit.get("slug", "channel"))
    existing = await db.execute(
        select(Channel).where(Channel.user_id == current_user.id, Channel.slug == slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug déjà utilisé")

    channel = Channel(
        user_id=current_user.id,
        slug=slug,
        name=str(brand_kit.get("name", slug)),
        theme_category=str(brand_kit.get("theme_category", "default")),
        niche_prompt=str(brand_kit.get("niche_prompt", "")),
        theme_prompt=body.theme_prompt,
        brand_kit=brand_kit,
        onboarding_step="brand",
        config=_config_from_brand_kit(brand_kit),
        composio_user_id=slug,
        is_active=False,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.get("/youtube/oauth-url", response_model=YouTubeOAuthUrlResponse)
async def youtube_oauth_url(
    channel_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> YouTubeOAuthUrlResponse:
    if channel_id:
        await get_user_channel(db, channel_id, current_user)
    state = create_oauth_state(
        user_id=current_user.id,
        channel_id=channel_id,
        purpose="youtube_connect",
    )
    try:
        url = youtube_branding.get_oauth_authorization_url(
            state=state,
            redirect_uri=settings.youtube_oauth_redirect_uri,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    return YouTubeOAuthUrlResponse(authorization_url=url, state=state)


@router.get("/youtube/oauth/callback")
async def youtube_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    try:
        payload = decode_oauth_state(state, expected_purpose="youtube_connect")
    except ValueError as exc:
        return RedirectResponse(
            url=_youtube_oauth_done_url(error=str(exc)),
            status_code=status.HTTP_302_FOUND,
        )

    channel_id_str = payload.get("channel_id")

    try:
        refresh_token = youtube_branding.exchange_oauth_code(
            code=code,
            redirect_uri=settings.youtube_oauth_redirect_uri,
        )
    except Exception as e:
        logger.error("OAuth YouTube échoué : %s", e)
        return RedirectResponse(
            url=_youtube_oauth_done_url(channel_id=channel_id_str, error=str(e)),
            status_code=status.HTTP_302_FOUND,
        )

    if channel_id_str:
        await db.execute(
            update(Channel)
            .where(Channel.id == uuid.UUID(channel_id_str))
            .values(youtube_refresh_token=refresh_token, onboarding_step="youtube")
        )
        await db.commit()

    return RedirectResponse(
        url=_youtube_oauth_done_url(channel_id=channel_id_str),
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/youtube/list", response_model=list[YouTubeChannelItem])
async def list_youtube_channels(
    channel_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[YouTubeChannelItem]:
    # Le token global (.env) ne liste que les chaînes de l'exploitant : admin uniquement.
    refresh_token = settings.youtube_refresh_token if current_user.is_admin else None
    if channel_id:
        ch = await get_user_channel(db, channel_id, current_user)
        refresh_token = await youtube_refresh_token(ch)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connectez d'abord la chaîne YouTube (OAuth)",
        )

    try:
        items = await youtube_branding.list_youtube_channels(refresh_token)
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e

    return [YouTubeChannelItem(**item) for item in items]


@router.delete("/{channel_id}/youtube/oauth")
async def disconnect_youtube_oauth(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    channel = await get_user_channel(db, channel_id, current_user)
    channel.youtube_refresh_token = None
    await db.commit()
    return {"status": "ok"}


@router.patch("/{channel_id}/onboarding/youtube", response_model=ChannelResponse)
async def patch_onboarding_youtube(
    channel_id: uuid.UUID,
    body: OnboardingYoutubeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    channel = await get_user_channel(db, channel_id, current_user)
    channel.youtube_channel_id = body.youtube_channel_id
    if body.youtube_channel_url:
        channel.youtube_channel_url = body.youtube_channel_url
    if body.youtube_refresh_token:
        channel.youtube_refresh_token = body.youtube_refresh_token
    channel.onboarding_step = "tiktok"
    await db.commit()
    await db.refresh(channel)
    return channel


@router.post("/{channel_id}/apply-youtube-branding")
async def apply_youtube_branding(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    channel = await get_user_channel(db, channel_id, current_user)
    if not channel.youtube_channel_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="youtube_channel_id manquant")
    if not channel.brand_kit or "youtube" not in channel.brand_kit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="brand_kit.youtube manquant")

    brand = YouTubeBrand(**channel.brand_kit["youtube"])
    token = await youtube_refresh_token(channel)
    try:
        await youtube_branding.update_channel_branding(
            channel.youtube_channel_id, brand, token
        )
    except Exception as e:
        logger.error("Apply branding YouTube : %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    # Génère et uploade la bannière en arrière-plan (non bloquant)
    from agent.skills.publisher.youtube_channel_manager import generate_and_upload_banner

    task = asyncio.create_task(generate_and_upload_banner(channel))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"status": "applied", "youtube_channel_id": channel.youtube_channel_id}


@router.post("/{channel_id}/onboarding/skip/{step}", response_model=ChannelResponse)
async def skip_onboarding_step(
    channel_id: uuid.UUID,
    step: Literal["youtube", "tiktok", "instagram"],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    channel = await get_user_channel(db, channel_id, current_user)
    next_step = ONBOARDING_SKIP_NEXT.get(step)
    if not next_step:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Étape invalide")
    _disable_platform_in_config(channel, step)
    channel.onboarding_step = next_step
    await db.commit()
    await db.refresh(channel)
    return channel


@router.patch("/{channel_id}/onboarding/tiktok", response_model=ChannelResponse)
async def patch_onboarding_tiktok(
    channel_id: uuid.UUID,
    body: OnboardingTikTokRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    channel = await get_user_channel(db, channel_id, current_user)
    if body.tiktok_publish_defaults is not None:
        channel.tiktok_publish_defaults = body.tiktok_publish_defaults
    channel.onboarding_step = "instagram"
    await db.commit()
    await db.refresh(channel)
    return channel


@router.patch("/{channel_id}/onboarding/instagram", response_model=ChannelResponse)
async def patch_onboarding_instagram(
    channel_id: uuid.UUID,
    body: OnboardingInstagramRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    channel = await get_user_channel(db, channel_id, current_user)
    channel.instagram_page_id = body.instagram_page_id
    if body.instagram_profile is not None:
        channel.instagram_profile = body.instagram_profile
    channel.onboarding_step = "complete"
    await db.commit()
    await db.refresh(channel)
    return channel


@router.post("/{channel_id}/onboarding/complete", response_model=ChannelResponse)
async def complete_onboarding(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    channel = await get_user_channel(db, channel_id, current_user)
    if channel.brand_kit:
        kit = ChannelBrandKit.model_validate(channel.brand_kit)
        channel.niche_prompt = kit.niche_prompt
        channel.name = kit.name
        channel.theme_category = kit.theme_category
        merged = _config_from_brand_kit(channel.brand_kit)
        existing = channel.config or {}
        for key, val in merged.items():
            if val is not None:
                if key in existing and isinstance(existing[key], dict) and isinstance(val, dict):
                    existing[key] = {**existing[key], **val}
                else:
                    existing[key] = val
        channel.config = existing
    channel.onboarding_step = "complete"
    channel.is_active = True
    await db.commit()
    await db.refresh(channel)

    return channel
