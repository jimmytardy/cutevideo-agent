from __future__ import annotations

import uuid
from datetime import datetime, UTC

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import Channel, Project, SubscriptionPlan, User, Video


class SubscriptionLimits(BaseModel):
    max_channels: int = 1
    max_projects_per_month: int = 5
    max_total_storage_bytes: int = 2 * 1024**3
    daily_quotas_short: int = 1
    max_long_duration_seconds: int = 900
    max_short_duration_s: int = 60
    production_modes: list[str] = Field(default_factory=lambda: ["mixed", "shorts_only"])
    auto_publish_allowed: bool = False
    max_critic_iterations: int = 2
    unlimited_critic_iterations: bool = False
    tts_allowed_engines: list[str] = Field(default_factory=lambda: ["edge"])
    whisper_model: str = "base"
    enable_ai_fallback: bool = False
    # Motion design 3D (style motion3d, plans 3D en style auto) : rendu long, réservé aux plans payants.
    motion3d_allowed: bool = False
    pipeline_queue_priority: int = 10


class QuotaExceededError(RuntimeError):
    def __init__(self, limit_key: str, message: str) -> None:
        self.limit_key = limit_key
        super().__init__(message)


async def load_user_with_plan(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_plan_for_user(session: AsyncSession, user: User) -> SubscriptionPlan:
    result = await session.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == user.subscription_id)
    )
    return result.scalar_one()


def is_unlimited(plan: SubscriptionPlan) -> bool:
    return bool(plan.is_unlimited)


async def sync_user_admin_flag(
    session: AsyncSession,
    user: User,
    plan: SubscriptionPlan | None = None,
) -> bool:
    """Aligne `user.is_admin` sur le plan d'abonnement et persiste si besoin.

    Appelée à chaque résolution de plan (login, /me) : tout porteur d'un plan
    illimité est automatiquement promu admin en BDD, et rétrogradé si son plan
    redevient limité.
    """
    if plan is None:
        plan = await get_plan_for_user(session, user)
    desired = is_unlimited(plan)
    if user.is_admin != desired:
        user.is_admin = desired
        await session.commit()
        await session.refresh(user)
    return user.is_admin


async def resolve_user_limits(session: AsyncSession, user: User) -> SubscriptionLimits:
    plan = await get_plan_for_user(session, user)
    if is_unlimited(plan):
        return SubscriptionLimits(
            max_channels=9999,
            max_projects_per_month=9999,
            max_total_storage_bytes=10**15,
            daily_quotas_short=9999,
            max_long_duration_seconds=7200,
            max_short_duration_s=180,
            production_modes=["mixed", "long_only", "shorts_only"],
            auto_publish_allowed=True,
            unlimited_critic_iterations=True,
            tts_allowed_engines=["edge", "azure", "gemini"],
            whisper_model="small",
            enable_ai_fallback=True,
            motion3d_allowed=True,
            pipeline_queue_priority=100,
        )
    raw = plan.limits or {}
    return SubscriptionLimits.model_validate(raw)


async def get_user_subscription_limits(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> SubscriptionLimits:
    user = await load_user_with_plan(session, user_id)
    if user is None:
        return SubscriptionLimits()
    return await resolve_user_limits(session, user)


def _tts_engine_key(engine: object) -> str:
    """`edge` et `edge-tts` désignent le même moteur."""
    name = str(engine or "").strip().lower()
    return "edge" if name == "edge-tts" else name


def apply_subscription_caps(
    channel_config_dict: dict,
    limits: SubscriptionLimits,
) -> dict:
    """Plafonne la config chaîne effective selon l'abonnement."""
    if not channel_config_dict:
        channel_config_dict = {}
    out = dict(channel_config_dict)

    publishing = dict(out.get("publishing") or {})
    quotas = dict(publishing.get("daily_quotas") or {})
    quotas["short"] = min(int(quotas.get("short", limits.daily_quotas_short)), limits.daily_quotas_short)
    publishing["daily_quotas"] = quotas
    if not limits.auto_publish_allowed:
        publishing["auto_publish"] = False
    out["publishing"] = publishing

    production = dict(out.get("production") or {})
    mode = str(production.get("mode", "mixed"))
    if mode not in limits.production_modes:
        production["mode"] = limits.production_modes[0]
    production["short_duration_s"] = min(
        int(production.get("short_duration_s", limits.max_short_duration_s)),
        limits.max_short_duration_s,
    )
    production["max_short_duration_s"] = min(
        int(production.get("max_short_duration_s", limits.max_short_duration_s)),
        limits.max_short_duration_s,
    )
    out["production"] = production

    if not limits.unlimited_critic_iterations:
        pipeline = dict(out.get("pipeline") or {})
        pipeline["max_critic_iterations"] = min(
            int(pipeline.get("max_critic_iterations", limits.max_critic_iterations)),
            limits.max_critic_iterations,
        )
        out["pipeline"] = pipeline

    content_planning = dict(out.get("content_planning") or {})
    content_planning["default_long_duration_seconds"] = min(
        int(content_planning.get("default_long_duration_seconds", limits.max_long_duration_seconds)),
        limits.max_long_duration_seconds,
    )
    out["content_planning"] = content_planning

    tts = dict(out.get("tts") or {})
    allowed = {_tts_engine_key(e) for e in limits.tts_allowed_engines}
    if _tts_engine_key(tts.get("engine", "edge")) not in allowed:
        tts["engine"] = limits.tts_allowed_engines[0]
    # Le brief Studio lit le profil `tts.short` : le plafond doit s'y appliquer aussi.
    for profile_key in ("short", "long"):
        profile = tts.get(profile_key)
        if isinstance(profile, dict) and _tts_engine_key(profile.get("engine", "")) not in allowed:
            tts[profile_key] = {
                k: v for k, v in profile.items() if k != "voice"
            } | {"engine": limits.tts_allowed_engines[0]}
    if "gemini" not in limits.tts_allowed_engines:
        gemini = dict(tts.get("gemini") or {})
        gemini["apply_to"] = "off"
        tts["gemini"] = gemini
    out["tts"] = tts

    whisper = dict(out.get("whisper") or {})
    whisper["model"] = limits.whisper_model
    out["whisper"] = whisper

    # Style motion3d sans droit : rétrogradé en animation (le kit 2D). « auto » n'a rien à réécrire : sans droit, la
    # 3D est simplement absente du brief (resolve_channel_config → studio_motion3d).
    studio = dict(out.get("studio") or {})
    if not limits.motion3d_allowed and studio.get("visual_style") == "motion3d":
        studio["visual_style"] = "animation"
        out["studio"] = studio

    media_sources = dict(out.get("media_sources") or {})
    media_sources["enable_ai_fallback"] = limits.enable_ai_fallback
    if not limits.enable_ai_fallback:
        ai_fallback = dict(media_sources.get("ai_fallback") or {})
        ai_fallback["enabled"] = False
        media_sources["ai_fallback"] = ai_fallback
    out["media_sources"] = media_sources

    return out


def resolve_effective_max_critic_iterations(
    *,
    project_config: dict,
    channel_max: int,
    limits: SubscriptionLimits,
) -> int | None:
    """Max effectif pour la boucle critique.

    None = illimité (admin sans plafond explicite dans project.config).
    """
    override = project_config.get("max_critic_iterations")
    if limits.unlimited_critic_iterations:
        return int(override) if override is not None else None
    capped = min(int(override), limits.max_critic_iterations) if override is not None else None
    return capped or min(channel_max, limits.max_critic_iterations)


async def count_user_channels(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Channel).where(Channel.user_id == user_id)
    )
    return int(result.scalar_one())


async def count_user_projects_this_month(session: AsyncSession, user_id: uuid.UUID) -> int:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(func.count())
        .select_from(Project)
        .join(Channel, Channel.id == Project.channel_id)
        .where(Channel.user_id == user_id, Project.created_at >= month_start)
    )
    return int(result.scalar_one())


async def sum_user_storage_bytes(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(Video.file_size_bytes), 0))
        .select_from(Video)
        .join(Project, Project.id == Video.project_id)
        .join(Channel, Channel.id == Project.channel_id)
        .where(
            Channel.user_id == user_id,
            Video.storage_key.isnot(None),
            Video.file_purged_at.is_(None),
        )
    )
    return int(result.scalar_one())


async def check_can_create_channel(session: AsyncSession, user: User) -> None:
    limits = await resolve_user_limits(session, user)
    current = await count_user_channels(session, user.id)
    if current >= limits.max_channels:
        raise QuotaExceededError(
            "max_channels",
            f"Limite de {limits.max_channels} chaîne(s) atteinte pour votre abonnement.",
        )


async def check_can_create_project(session: AsyncSession, user: User) -> None:
    limits = await resolve_user_limits(session, user)
    current = await count_user_projects_this_month(session, user.id)
    if current >= limits.max_projects_per_month:
        raise QuotaExceededError(
            "max_projects_per_month",
            f"Limite de {limits.max_projects_per_month} projet(s) / mois atteinte.",
        )
