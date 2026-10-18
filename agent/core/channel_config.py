from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from agent.core.config import load_agent_config
from agent.core.editorial_formats import (
    EditorialFormatDefinition,
    EditorialFormatRotationConfig,
    resolve_editorial_formats,
    resolve_format_rotation_config,
)
from agent.core.database import Channel
from studio.contracts import VISUAL_STYLES

if TYPE_CHECKING:
    from agent.core.subscription import SubscriptionLimits

logger = logging.getLogger(__name__)

# Anciens noms de plan encore présents dans des `Channel.config`.
PLAN_LEGACY_ALIASES: dict[str, str] = {
    "budget": "flux_schnell",
    "balanced": "flux_pro",
    "quality": "flux_ultra",
}


class AiImagePlan(str, Enum):
    OFF = "off"
    FLUX_SCHNELL = "flux_schnell"
    FLUX_PRO = "flux_pro"
    FLUX_ULTRA = "flux_ultra"
    FLUX_2_DEV = "flux_2_dev"
    IMAGEN3_FAST = "imagen3_fast"
    IMAGEN3 = "imagen3"


class AiFallbackConfig(BaseModel):
    """Images IA de Claude Studio (`ai-image`) : `plan` = modèle par défaut et plafond de prix
    (Claude peut choisir un modèle moins cher, cf. `models_up_to`)."""

    enabled: bool = True
    plan: AiImagePlan = AiImagePlan.FLUX_PRO
    max_ai_images_per_video: int = 10


DEFAULT_PLATFORMS = ["youtube", "tiktok", "instagram"]


class DailyQuotasConfig(BaseModel):
    long: int = 1
    short: int = 3


class GeminiTtsConfig(BaseModel):
    apply_to: Literal["off", "shorts", "long", "both"] = "off"
    model: str = "gemini-2.5-flash-preview-tts"
    voice: str = "Puck"
    language_code: str = "fr"


TtsEngine = Literal["azure", "gemini", "edge-tts"]


class TtsFormatProfile(BaseModel):
    """Moteur et voix TTS pour un format vidéo (short ou long)."""

    engine: TtsEngine = "azure"
    voice: str = "fr-FR-Vivienne:DragonHDLatestNeural"


class ChannelRuntimeConfig(BaseModel):
    """Réglages effectifs d'une chaîne (défauts Pydantic < data/agent_config.json < Channel.config)."""

    # Voix : `tts_short` est le profil lu par le brief Studio ; engine/voice = défauts legacy.
    tts_engine: str = "azure"
    tts_voice: str = "fr-FR-Vivienne:DragonHDLatestNeural"
    tts_short: TtsFormatProfile = Field(default_factory=TtsFormatProfile)
    # Publication (DistributionAgent / executor)
    default_tags: list[str] = Field(default_factory=list)
    youtube_category_id: str = "27"
    auto_publish: bool = False
    timezone: str = "Europe/Paris"
    daily_quotas: DailyQuotasConfig = Field(default_factory=DailyQuotasConfig)
    platform_slots: dict[str, dict[str, list[int]]] = Field(default_factory=dict)
    enabled_platforms: list[str] = Field(default_factory=lambda: list(DEFAULT_PLATFORMS))
    # Planification (ContentPlannerAgent)
    production_mode: Literal["mixed", "long_only", "shorts_only"] = "mixed"
    short_duration_s: int = 90
    min_duration_tiktok: int = 60
    editorial_tone: str = ""
    editorial_formats: list[EditorialFormatDefinition] = Field(default_factory=list)
    format_rotation: EditorialFormatRotationConfig = Field(default_factory=EditorialFormatRotationConfig)
    content_language: str = "fr"
    # Création Claude Studio
    # Animations : off | templates | scripts (data/agent_config.json → studio, surcharge chaîne).
    studio_animations: Literal["off", "templates", "scripts"] = "scripts"
    # Style visuel : animation | mixed | realistic (data/agent_config.json → studio.visual_style, surcharge chaîne).
    studio_visual_style: Literal["animation", "mixed", "realistic"] = "animation"
    # Boucle vidéo (monteur ⇄ analyse vidéo) puis boucle scénario (scénariste ⇄ analyse scénario).
    min_critic_score: int = 80
    max_critic_iterations: int = 5
    min_scenario_score: int = 90
    max_scenario_iterations: int = 5
    cost_max_per_video_usd: float = 8.0
    ai_fallback: AiFallbackConfig = Field(default_factory=AiFallbackConfig)


def _resolve_content_language(
    channel_overrides: dict[str, Any],
    global_cfg: dict[str, Any],
    tts_voice: str,
) -> str:
    whisper = channel_overrides.get("whisper") or {}
    if isinstance(whisper, dict) and whisper.get("language"):
        return str(whisper["language"])[:8]
    global_whisper = global_cfg.get("whisper", {})
    if isinstance(global_whisper, dict) and global_whisper.get("language"):
        return str(global_whisper["language"])[:8]
    if "-" in tts_voice:
        return tts_voice.split("-", 1)[0].lower()
    return "fr"


def _resolve_gemini_tts(tts: dict[str, Any]) -> GeminiTtsConfig:
    gemini = tts.get("gemini", {})
    if not isinstance(gemini, dict):
        gemini = {}
    apply_to = str(gemini.get("apply_to", "off"))
    if apply_to not in ("off", "shorts", "long", "both"):
        apply_to = "off"
    return GeminiTtsConfig(
        apply_to=apply_to,  # type: ignore[arg-type]
        model=str(gemini.get("model", "gemini-2.5-flash-preview-tts")),
        voice=str(gemini.get("voice", "Puck")),
        language_code=str(gemini.get("language_code", "fr")),
    )


DEFAULT_EDGE_VOICE = "fr-FR-RemyMultilingualNeural"


def _normalize_tts_engine(raw: str) -> TtsEngine:
    engine = str(raw or "azure").strip().lower()
    if engine == "edge":  # nom court utilisé par les plafonds d'abonnement et `studio.tools tts`
        return "edge-tts"
    if engine in ("azure", "gemini", "edge-tts"):
        return engine  # type: ignore[return-value]
    return "azure"


def _parse_tts_format_profile(
    raw: dict[str, Any] | None,
    *,
    fallback_engine: str,
    fallback_voice: str,
    edge_voice: str = DEFAULT_EDGE_VOICE,
) -> TtsFormatProfile:
    if not isinstance(raw, dict):
        raw = {}
    engine = _normalize_tts_engine(str(raw.get("engine", fallback_engine)))
    voice = str(raw.get("voice") or fallback_voice)
    if engine == "edge-tts" and ":" in voice:  # voix Azure HD (`…:DragonHDLatestNeural`) inconnue d'edge-tts
        voice = edge_voice
    return TtsFormatProfile(engine=engine, voice=voice)


def _resolve_tts_format_profiles(
    tts: dict[str, Any],
    gemini_tts: GeminiTtsConfig,
) -> tuple[TtsFormatProfile, TtsFormatProfile]:
    """Profils voix short/long — compat legacy engine/voice + gemini.apply_to."""
    default_engine = str(tts.get("engine", "azure"))
    default_voice = str(tts.get("voice", "fr-FR-Vivienne:DragonHDLatestNeural"))
    edge_voice = str(tts.get("fallback_voice") or DEFAULT_EDGE_VOICE)
    gemini_profile = TtsFormatProfile(engine="gemini", voice=gemini_tts.voice)
    default_profile = _parse_tts_format_profile(
        None, fallback_engine=default_engine, fallback_voice=default_voice, edge_voice=edge_voice
    )

    short_raw = tts.get("short")
    long_raw = tts.get("long")
    if isinstance(short_raw, dict) or isinstance(long_raw, dict):
        return (
            _parse_tts_format_profile(
                short_raw if isinstance(short_raw, dict) else None,
                fallback_engine=default_engine,
                fallback_voice=default_voice,
                edge_voice=edge_voice,
            ),
            _parse_tts_format_profile(
                long_raw if isinstance(long_raw, dict) else None,
                fallback_engine=default_engine,
                fallback_voice=default_voice,
                edge_voice=edge_voice,
            ),
        )

    apply_to = gemini_tts.apply_to
    if apply_to == "shorts":
        return gemini_profile, default_profile
    if apply_to == "long":
        return default_profile, gemini_profile
    if apply_to == "both":
        return gemini_profile, gemini_profile
    return default_profile, default_profile


def _resolve_ai_fallback(
    global_media: dict[str, Any], channel_overrides: dict[str, Any]
) -> AiFallbackConfig:
    global_cfg = global_media.get("ai_fallback", {})
    media_channel = channel_overrides.get("media_sources", {})
    if not isinstance(media_channel, dict):
        media_channel = {}
    ai_channel = media_channel.get("ai_fallback", {}) or {}
    # `media_sources.enable_ai_fallback` est l'interrupteur plafonné par l'abonnement.
    switch_on = bool(media_channel.get("enable_ai_fallback", True))

    raw_plan = str(ai_channel.get("plan", global_cfg.get("default_plan", "flux_pro")))
    normalized_plan = PLAN_LEGACY_ALIASES.get(raw_plan, raw_plan)
    try:
        plan = AiImagePlan(normalized_plan)
    except ValueError:
        plan = AiImagePlan.FLUX_PRO

    return AiFallbackConfig(
        enabled=switch_on and bool(ai_channel.get("enabled", global_cfg.get("enabled", True))),
        plan=plan,
        max_ai_images_per_video=int(
            ai_channel.get(
                "max_ai_images_per_video",
                global_cfg.get("max_ai_images_per_video", 10),
            )
        ),
    )


def _tags_from_channel(channel: Channel) -> list[str]:
    if channel.config and channel.config.get("publishing", {}).get("default_tags"):
        return list(channel.config["publishing"]["default_tags"])
    if channel.brand_kit and channel.brand_kit.get("default_tags"):
        return [str(t) for t in channel.brand_kit["default_tags"]]
    return []


def resolve_channel_config(
    channel: Channel,
    *,
    subscription_limits: SubscriptionLimits | None = None,
) -> ChannelRuntimeConfig:
    """Fusionne agent_config.json global et channel.config (surcharges)."""
    from agent.core.subscription import apply_subscription_caps

    global_cfg = load_agent_config()
    channel_overrides: dict[str, Any] = dict(channel.config or {})
    if subscription_limits is not None:
        channel_overrides = apply_subscription_caps(channel_overrides, subscription_limits)

    pipeline = {**global_cfg.get("pipeline", {}), **channel_overrides.get("pipeline", {})}
    # Ancienne clé `quality.max_iterations` d'une chaîne : reprise tant qu'elle n'a pas de plafond `pipeline`.
    legacy_quality = channel_overrides.get("quality") or {}
    if "max_critic_iterations" not in (channel_overrides.get("pipeline") or {}) and "max_iterations" in legacy_quality:
        pipeline["max_critic_iterations"] = legacy_quality["max_iterations"]
    cost_cfg = {**global_cfg.get("cost", {}), **channel_overrides.get("cost", {})}
    tts = {**global_cfg.get("tts", {}), **channel_overrides.get("tts", {})}
    tts_voice = str(tts.get("voice", "fr-FR-Vivienne:DragonHDLatestNeural"))
    publishing = {**global_cfg.get("publishing", {}), **channel_overrides.get("publishing", {})}
    production = channel_overrides.get("production", {})
    content_planning = global_cfg.get("content_planning", {})
    studio_cfg = {**global_cfg.get("studio", {}), **channel_overrides.get("studio", {})}
    studio_animations = str(studio_cfg.get("animations", "scripts"))
    if studio_animations not in ("off", "templates", "scripts"):
        studio_animations = "scripts"
    studio_visual_style = str(studio_cfg.get("visual_style", "animation"))
    if studio_visual_style not in VISUAL_STYLES:
        studio_visual_style = "animation"

    raw_quotas = publishing.get("daily_quotas", {})
    daily_quotas = DailyQuotasConfig(
        long=int(raw_quotas.get("long", 1)),
        short=int(raw_quotas.get("short", 3)),
    )
    production_mode = str(production.get("mode", "mixed"))
    if production_mode not in ("mixed", "long_only", "shorts_only"):
        production_mode = "mixed"
    if production_mode == "long_only":
        daily_quotas = DailyQuotasConfig(long=daily_quotas.long, short=0)
    elif production_mode == "shorts_only":
        daily_quotas = DailyQuotasConfig(long=0, short=daily_quotas.short or 3)

    tts_short, _tts_long = _resolve_tts_format_profiles(tts, _resolve_gemini_tts(tts))

    return ChannelRuntimeConfig(
        tts_engine=str(tts.get("engine", "azure")),
        tts_voice=tts_voice,
        tts_short=tts_short,
        default_tags=list(publishing.get("default_tags", [])) or _tags_from_channel(channel),
        youtube_category_id=str(publishing.get("youtube_category_id", "27")),
        auto_publish=bool(publishing.get("auto_publish", False)),
        timezone=str(publishing.get("timezone", "Europe/Paris")),
        daily_quotas=daily_quotas,
        platform_slots=dict(publishing.get("platform_slots", {})),
        enabled_platforms=list(publishing.get("enabled_platforms", DEFAULT_PLATFORMS)),
        production_mode=production_mode,  # type: ignore[arg-type]
        short_duration_s=int(
            production.get("short_duration_s", content_planning.get("default_short_duration_s", 60))
        ),
        min_duration_tiktok=int(
            global_cfg.get("video", {}).get("short", {}).get("min_duration_tiktok", 60)
        ),
        editorial_tone=str(channel_overrides.get("editorial", {}).get("tone", "")),
        editorial_formats=resolve_editorial_formats(channel_overrides),
        format_rotation=resolve_format_rotation_config(channel_overrides),
        content_language=_resolve_content_language(channel_overrides, global_cfg, tts_voice),
        studio_animations=studio_animations,  # type: ignore[arg-type]
        studio_visual_style=studio_visual_style,  # type: ignore[arg-type]
        min_critic_score=int(pipeline.get("min_critic_score", 80)),
        max_critic_iterations=int(pipeline.get("max_critic_iterations", 5)),
        min_scenario_score=int(pipeline.get("min_scenario_score", 90)),
        max_scenario_iterations=int(pipeline.get("max_scenario_iterations", 5)),
        cost_max_per_video_usd=float(cost_cfg.get("max_per_video_usd", 8.0)),
        ai_fallback=_resolve_ai_fallback(global_cfg.get("media_sources", {}), channel_overrides),
    )
