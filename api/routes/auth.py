from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import httpx
from urllib.parse import urlencode, urlparse, urlunparse
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.auth import create_access_token, create_oauth_state, decode_oauth_state
from agent.core.config import settings
from agent.core.database import SubscriptionPlan, User, get_db
from api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class AuthUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    avatar_url: str | None
    plan_slug: str
    is_admin: bool

    model_config = {"from_attributes": True}


class LoginUrlResponse(BaseModel):
    authorization_url: str
    state: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


MIGRATION_SYSTEM_GOOGLE_SUB = "migration-system"


async def _get_plan_by_slug(db: AsyncSession, slug: str) -> SubscriptionPlan:
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.slug == slug))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=500, detail=f"Plan d'abonnement « {slug} » introuvable")
    return plan


async def _get_default_plan(db: AsyncSession) -> SubscriptionPlan:
    return await _get_plan_by_slug(db, "free")


async def _count_real_users(db: AsyncSession) -> int:
    """Compte les utilisateurs réels (hors compte technique de migration)."""
    result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(User.google_sub != MIGRATION_SYSTEM_GOOGLE_SUB)
    )
    return int(result.scalar_one())


def _resolve_login_redirect(extra: dict) -> str:
    """Retourne l'URL frontend où déposer le JWT (toujours /login si seule l'origine est fournie)."""
    redirect_after = extra.get("redirect_after") or settings.cors_origins.split(",")[0].strip()
    parsed = urlparse(redirect_after)
    if parsed.path in ("", "/"):
        parsed = parsed._replace(path="/login")
    return urlunparse(parsed)


async def _get_plan_for_new_user(db: AsyncSession) -> SubscriptionPlan:
    """Le premier inscrit réel reçoit le plan admin ; les suivants le plan free."""
    if await _count_real_users(db) == 0:
        logger.info("Premier utilisateur inscrit — attribution du plan admin")
        return await _get_plan_by_slug(db, "admin")
    return await _get_default_plan(db)


@router.get("/google/login", response_model=LoginUrlResponse)
async def google_login(redirect_after: str | None = Query(default=None)) -> LoginUrlResponse:
    if not settings.google_oauth_client_id:
        raise HTTPException(status_code=503, detail="Google OAuth non configuré")
    extra = {"redirect_after": redirect_after} if redirect_after else None
    state = create_oauth_state(purpose="google_login", extra=extra)
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    query = urlencode(params)
    return LoginUrlResponse(
        authorization_url=f"{GOOGLE_AUTH_URL}?{query}",
        state=state,
    )


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    try:
        payload = decode_oauth_state(state, expected_purpose="google_login")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth non configuré")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            logger.error("Google token error: %s", token_resp.text)
            raise HTTPException(status_code=400, detail="Échec échange token Google")
        tokens = token_resp.json()
        access = tokens.get("access_token")
        if not access:
            raise HTTPException(status_code=400, detail="Token Google absent")

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access}"},
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Profil Google inaccessible")
        profile = userinfo_resp.json()

    google_sub = str(profile.get("sub", ""))
    email = str(profile.get("email", ""))
    if not google_sub or not email:
        raise HTTPException(status_code=400, detail="Profil Google incomplet")

    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()
    if user is None:
        plan = await _get_plan_for_new_user(db)
        user = User(
            google_sub=google_sub,
            email=email,
            display_name=profile.get("name"),
            avatar_url=profile.get("picture"),
            subscription_id=plan.id,
            subscription_started_at=datetime.now(timezone.utc),
        )
        db.add(user)
    else:
        user.email = email
        user.display_name = profile.get("name") or user.display_name
        user.avatar_url = profile.get("picture") or user.avatar_url
        user.is_active = True
    await db.commit()
    await db.refresh(user)

    jwt_token = create_access_token(user.id)
    extra = payload.get("extra") or {}
    redirect_base = _resolve_login_redirect(extra)
    query = urlencode({"token": jwt_token})
    sep = "&" if "?" in redirect_base else "?"
    return RedirectResponse(
        url=f"{redirect_base}{sep}{query}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/me", response_model=AuthUserResponse)
async def auth_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuthUserResponse:
    from agent.core.subscription import get_plan_for_user, is_unlimited

    plan = await get_plan_for_user(db, user)
    return AuthUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        plan_slug=plan.slug,
        is_admin=is_unlimited(plan),
    )


@router.post("/logout")
async def logout() -> dict[str, str]:
    return {"status": "ok"}
