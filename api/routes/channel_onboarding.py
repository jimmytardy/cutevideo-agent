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

from agent.agents.channel_planner_agent import ChannelPlannerAgent
from agent.skills.market_research.youtube_discovery import YouTubeAuthError
from agent.core.auth import create_oauth_state, decode_oauth_state
from agent.core.channel_brand import ChannelBrandKit, ThemeVariant, YouTubeBrand
from agent.core.config import settings
from agent.core.database import Channel, MarketAnalysis, User, get_db
from agent.core.subscription import QuotaExceededError, check_can_create_channel, check_can_run_market_analysis
from agent.skills.publisher import youtube_branding
from api.authorization import get_user_channel
from api.deps import get_current_user
from api.models import (
    ChannelResponse,
    GenerateBrandRequest,
    MarketAnalysisRequest,
    MarketAnalysisResponse,
    OnboardingCompleteRequest,
    OnboardingDraftRequest,
    OnboardingInstagramRequest,
    OnboardingTikTokRequest,
    OnboardingYoutubeRequest,
    SuggestThemesRequest,
    SuggestThemesResponse,
    ThemeVariantResponse,
    YouTubeChannelItem,
    YouTubeOAuthUrlResponse,
)

logger = logging.getLogger(__name__)

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


@router.post("/onboarding/market-analysis", response_model=MarketAnalysisResponse)
async def market_analysis(
    body: MarketAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MarketAnalysisResponse:
    """Analyse marché, concurrence et niches (YouTube API + synthèse multi-plateformes)."""
    try:
        await check_can_run_market_analysis(db, current_user)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    planner = ChannelPlannerAgent()
    planner.bind_user(current_user.id)
    try:
        report = await planner.analyze_market(
            body.prompt,
            platforms=body.platforms,
            region=body.region,
            language=body.language,
        )
    except YouTubeAuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception("Erreur inattendue lors de l'analyse marché")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    report_dict = report.model_dump()
    saved = MarketAnalysis(
        user_id=current_user.id,
        prompt=body.prompt,
        saturation_verdict=report.saturation_verdict,
        market_summary=report.market_summary,
        platforms_analyzed=report.platforms_analyzed,
        report=report_dict,
    )
    db.add(saved)
    await db.commit()
    await db.refresh(saved)

    response = MarketAnalysisResponse.model_validate(report_dict)
    response.id = saved.id
    return response


@router.post("/onboarding/suggest-themes", response_model=SuggestThemesResponse)
async def suggest_themes(body: SuggestThemesRequest) -> SuggestThemesResponse:
    planner = ChannelPlannerAgent()
    variants = await planner.suggest_theme_variants(
        body.prompt,
        market_context=body.market_context,
    )
    return SuggestThemesResponse(
        variants=[ThemeVariantResponse.model_validate(v.model_dump()) for v in variants]
    )


@router.post("/onboarding/generate-brand")
async def generate_brand(body: GenerateBrandRequest) -> dict[str, Any]:
    planner = ChannelPlannerAgent()
    variant = ThemeVariant.model_validate(body.variant.model_dump())
    kit = await planner.generate_brand_kit(variant, market_hint=body.market_context)
    return kit.model_dump()


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
    refresh_token: str | None = settings.youtube_refresh_token or None
    if channel_id:
        ch = await get_user_channel(db, channel_id, current_user)
        if ch.youtube_refresh_token:
            refresh_token = ch.youtube_refresh_token

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
    channel = await _get_channel_for_user(db, channel_id, current_user)
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
    channel = await _get_channel_for_user(db, channel_id, current_user)
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
    channel = await _get_channel_for_user(db, channel_id, current_user)
    if not channel.youtube_channel_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="youtube_channel_id manquant")
    if not channel.brand_kit or "youtube" not in channel.brand_kit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="brand_kit.youtube manquant")

    brand = YouTubeBrand(**channel.brand_kit["youtube"])
    token = channel.youtube_refresh_token or settings.youtube_refresh_token or None
    try:
        await youtube_branding.update_channel_branding(
            channel.youtube_channel_id, brand, token
        )
    except Exception as e:
        logger.error("Apply branding YouTube : %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    # Génère et uploade la bannière en arrière-plan (non bloquant)
    import asyncio as _asyncio

    from agent.skills.publisher.youtube_channel_manager import generate_and_upload_banner
    _asyncio.create_task(generate_and_upload_banner(channel))

    return {"status": "applied", "youtube_channel_id": channel.youtube_channel_id}


@router.post("/{channel_id}/onboarding/skip/{step}", response_model=ChannelResponse)
async def skip_onboarding_step(
    channel_id: uuid.UUID,
    step: Literal["youtube", "tiktok", "instagram"],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    channel = await _get_channel_for_user(db, channel_id, current_user)
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
    channel = await _get_channel_for_user(db, channel_id, current_user)
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
    channel = await _get_channel_for_user(db, channel_id, current_user)
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
    body: OnboardingCompleteRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    channel = await _get_channel_for_user(db, channel_id, current_user)
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
    # Demande à l'IA de choisir l'ordre optimal des sources médias pour cette chaîne
    from agent.skills.media_sources.source_advisor import suggest_media_source_priority
    priority = await suggest_media_source_priority(
        channel_name=channel.name,
        theme_category=channel.theme_category or "",
        niche_prompt=channel.niche_prompt or "",
        user_id=current_user.id,
    )
    if priority:
        cfg = channel.config or {}
        cfg["media_source_priority"] = priority
        channel.config = cfg

    if body and body.market_analysis_id:
        ma_result = await db.execute(
            select(MarketAnalysis).where(
                MarketAnalysis.id == body.market_analysis_id,
                MarketAnalysis.user_id == current_user.id,
            )
        )
        market_row = ma_result.scalar_one_or_none()
        if market_row and isinstance(market_row.report, dict):
            report = market_row.report
            cfg = channel.config or {}
            cfg["market_research"] = {
                "top_competitors": report.get("top_competitors", []),
                "captured_at": market_row.created_at.isoformat()
                if market_row.created_at
                else None,
                "market_analysis_id": str(market_row.id),
            }
            channel.config = cfg

    channel.onboarding_step = "complete"
    channel.is_active = True
    await db.commit()
    await db.refresh(channel)

    from agent.agents.style_director_agent import StyleDirectorAgent

    async def _run_style_director() -> None:
        try:
            await StyleDirectorAgent().run_for_channel(channel.id, force=True)
        except Exception:
            logger.exception("StyleDirector post-onboarding échoué pour %s", channel.slug)

    asyncio.create_task(_run_style_director())
    return channel


async def _get_channel_for_user(
    db: AsyncSession, channel_id: uuid.UUID, user: User
) -> Channel:
    return await get_user_channel(db, channel_id, user)
