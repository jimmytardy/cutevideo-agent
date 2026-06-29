from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel, Field

from agent.core.config import load_agent_config
from agent.core.editorial_formats import (
    EditorialFormatDefinition,
    EditorialFormatRotationConfig,
    resolve_editorial_formats,
    resolve_format_rotation_config,
)
from agent.core.database import Channel

logger = logging.getLogger(__name__)

PLAN_LEGACY_ALIASES: dict[str, str] = {
    "off": "off",
    "budget": "flux_schnell",
    "balanced": "flux_pro",
    "quality": "flux_ultra",
    "flux_schnell": "flux_schnell",
    "flux_pro": "flux_pro",
    "flux_ultra": "flux_ultra",
    "imagen3_fast": "imagen3_fast",
    "imagen3": "imagen3",
}


class AiImagePlan(str, Enum):
    OFF = "off"
    FLUX_SCHNELL = "flux_schnell"
    FLUX_PRO = "flux_pro"
    FLUX_ULTRA = "flux_ultra"
    IMAGEN3_FAST = "imagen3_fast"
    IMAGEN3 = "imagen3"


class AiFallbackConfig(BaseModel):
    enabled: bool = True
    plan: AiImagePlan = AiImagePlan.FLUX_PRO
    fallback_chain: list[str] = Field(default_factory=lambda: ["imagen3"])
    max_images_per_segment: int = 2
    max_ai_images_per_video: int = 10
    max_ai_images_per_week: int | None = None
    fallback_rate_override: float | None = None

    def resolved_provider_chain(self) -> list[str]:
        if self.plan == AiImagePlan.OFF or not self.enabled:
            return []
        primary = self.plan.value
        chain = [primary]
        for item in self.fallback_chain:
            normalized = PLAN_LEGACY_ALIASES.get(item, item)
            if normalized != "off" and normalized != primary and normalized not in chain:
                chain.append(normalized)
        return chain


class RunwayConfig(BaseModel):
    enabled: bool = False
    monthly_budget_usd: float = 20.0
    cost_per_second_usd: float = 0.05  # Gen-4 Turbo ~$0.05/s at 720p
    default_duration_s: Literal[5, 10] = 5
    model: str = "gen4_turbo"
    resolution: str = "1280:720"
    max_clips_per_video: int = 3
    max_clips_per_short: int = 1


THEME_SOURCE_PRIORITY: dict[str, list[str]] = {
    "histoire":   ["gallica", "europeana", "wikimedia", "internet_archive", "pexels"],
    "france":     ["gallica", "europeana", "wikimedia", "pexels"],
    "nature":     ["unsplash", "pexels", "pixabay", "coverr", "wikimedia", "internet_archive"],
    "animaux":    ["pexels", "pixabay", "coverr", "wikimedia", "internet_archive", "unsplash"],
    "science":    ["nasa", "wikimedia", "pexels", "pixabay", "coverr"],
    "art":        ["europeana", "wikimedia", "unsplash"],
    "finance":    ["pexels", "unsplash", "pixabay", "coverr", "wikimedia"],
    "psychologie": ["pexels", "unsplash", "pixabay", "coverr", "wikimedia"],
    "true_crime": ["wikimedia", "pexels", "internet_archive", "pixabay", "coverr"],
    "sport":      ["pexels", "pixabay", "coverr", "wikimedia", "unsplash"],
    "tech":       ["pexels", "unsplash", "pixabay", "coverr", "wikimedia"],
    "entertainment": ["coverr", "pexels", "pixabay", "wikimedia"],
    "humour":     ["coverr", "pexels", "pixabay", "wikimedia"],
    "default":    ["pexels", "pixabay", "coverr", "unsplash", "wikimedia", "internet_archive"],
}

DEFAULT_PLATFORMS = ["youtube", "tiktok", "instagram"]


class DailyQuotasConfig(BaseModel):
    long: int = 1
    short: int = 3


class MediaSourcesConfig(BaseModel):
    priority: list[str] = Field(default_factory=list)
    min_candidates_per_segment: int = 4
    enable_ai_fallback: bool = True
    images_per_segment: int = 3
    prefer_video: bool = True
    video_clips_per_segment: int = 2
    min_width_px: int = 1280
    relevance_min_score: int = 60
    max_search_iterations: int = 3
    min_passing_candidates_multiplier: float = 1.5
    relevance_min_score_high_precision: int = 75
    niche_threshold_candidates: int = 2
    enable_post_selection_audit: bool = True
    # Plancher de qualité : on n'expédie jamais un visuel (stock ou IA) dont le
    # meilleur score de pertinence est sous ce seuil — il devient un media gap.
    forced_best_min_score: int = 40


class VisualBeatsConfig(BaseModel):
    enabled: bool = True
    min_beats_per_short_segment: int = 3
    max_beats_per_segment: int = 8
    min_diagram_duration_s: float = 6.0
    min_diagram_duration_short_s: float = 4.0


class MediaLibraryConfig(BaseModel):
    enabled: bool = True
    pool_min_score: int = 70
    reuse_min_score: int = 80
    max_pool_size_per_project: int = 100
    scope: str = "project"


class ShortDerivationConfig(BaseModel):
    strategy: Literal["crop", "native", "hybrid"] = "hybrid"
    mode: Literal["reuse_pool_only", "free_sources_only", "full"] = "free_sources_only"
    hybrid_teaser_max_clips: int = 2


class GeminiTtsConfig(BaseModel):
    apply_to: Literal["off", "shorts", "long", "both"] = "off"
    model: str = "gemini-2.5-flash-preview-tts"
    voice: str = "Leda"
    language_code: str = "fr"


TtsEngine = Literal["azure", "gemini", "edge-tts"]


class TtsFormatProfile(BaseModel):
    """Moteur et voix TTS pour un format vidéo (short ou long)."""

    engine: TtsEngine = "azure"
    voice: str = "fr-FR-Vivienne:DragonHDLatestNeural"


class AudioMasteringCompressorConfig(BaseModel):
    threshold_db: float = -18
    ratio: float = 3
    attack_ms: float = 15
    release_ms: float = 120
    makeup_db: float = 2


class AudioMasteringEqBand(BaseModel):
    f: int
    g: float
    w: float = 1.0


class AudioMasteringConfig(BaseModel):
    """Chaîne de mastering voix appliquée avant le loudnorm final (preset voice-studio)."""

    enabled: bool = True
    preset: str = "voice-studio"
    highpass_hz: int = 80
    deesser: bool = True
    compressor: AudioMasteringCompressorConfig = Field(
        default_factory=AudioMasteringCompressorConfig
    )
    eq: list[AudioMasteringEqBand] = Field(
        default_factory=lambda: [
            AudioMasteringEqBand(f=200, g=-2, w=1),
            AudioMasteringEqBand(f=3000, g=2, w=2),
        ]
    )


class SubtitleConfig(BaseModel):
    enabled: bool = True
    style: Literal["karaoke"] = "karaoke"
    max_words_per_line: int = 3
    pause_threshold_ms: int = 400
    font_name: str = "DejaVu Sans"
    font_size: int = 68
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFE600"
    outline_color: str = "#000000"
    outline_width: int = 4
    vertical_position: float = 0.65
    margin_v: int = 120
    play_res_x: int = 1080
    play_res_y: int = 1920
    active_word_scale: int = 115
    uppercase_highlight: bool = True
    uppercase_word_scale: int = 120


class ChannelRuntimeConfig(BaseModel):
    media_source_priority: list[str] = Field(default_factory=lambda: THEME_SOURCE_PRIORITY["default"])
    media_sources: MediaSourcesConfig = Field(default_factory=MediaSourcesConfig)
    tts_engine: str = "azure"
    tts_voice: str = "fr-FR-Vivienne:DragonHDLatestNeural"
    tts_fallback_voice: str = "fr-FR-DeniseNeural"
    tts_style: str = "narration-relaxed"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"
    tts_insert_pauses: bool = True
    tts_comma_pauses: bool = False
    tts_oralize: bool = True
    audio_mastering: AudioMasteringConfig = Field(default_factory=AudioMasteringConfig)
    gemini_tts: GeminiTtsConfig = Field(default_factory=GeminiTtsConfig)
    tts_short: TtsFormatProfile = Field(default_factory=TtsFormatProfile)
    tts_long: TtsFormatProfile = Field(default_factory=TtsFormatProfile)
    default_tags: list[str] = Field(default_factory=list)
    youtube_category_id: str = "27"
    auto_publish: bool = False
    timezone: str = "Europe/Paris"
    daily_quotas: DailyQuotasConfig = Field(default_factory=DailyQuotasConfig)
    platform_slots: dict[str, dict[str, list[int]]] = Field(default_factory=dict)
    enabled_platforms: list[str] = Field(default_factory=lambda: list(DEFAULT_PLATFORMS))
    production_mode: Literal["mixed", "long_only", "shorts_only"] = "mixed"
    short_duration_s: int = 90
    min_short_duration_s: int = 60
    max_short_duration_s: int = 120
    min_duration_tiktok: int = 60
    editorial_tone: str = ""
    editorial_target_audience: str = "Grand public curieux, français"
    editorial_differentiator: str = ""
    editorial_formats: list[EditorialFormatDefinition] = Field(default_factory=list)
    format_rotation: EditorialFormatRotationConfig = Field(default_factory=EditorialFormatRotationConfig)
    creative_brief: str = ""
    min_critic_score: int = 90
    min_short_structure_score: int = 15
    max_critic_iterations: int = 5
    max_fact_check_iterations: int = 3
    min_image_duration_s: int = 4
    min_image_duration_short_s: int = 1
    max_static_shot_s: int = 8
    content_language: str = "fr"
    music_theme: str = "default"
    auto_reply_comments: bool = True
    max_replies_per_run: int = 10
    max_comments_fetched: int = 50
    # Sécurité des réponses sortantes (OWASP LLM01 — action sortante dérivée d'entrée non fiable).
    reply_llm_screen: bool = True  # 2e couche : classifieur LLM léger avant publication
    require_reply_review: bool = False  # file de validation humaine au lieu de poster directement
    analytics_enabled: bool = True
    comments_enabled: bool = True
    max_publications_per_engagement_run: int = 40
    ai_fallback: AiFallbackConfig = Field(default_factory=AiFallbackConfig)
    runway: RunwayConfig = Field(default_factory=RunwayConfig)
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)
    visual_beats: VisualBeatsConfig = Field(default_factory=VisualBeatsConfig)
    media_library: MediaLibraryConfig = Field(default_factory=MediaLibraryConfig)
    short_derivation: ShortDerivationConfig = Field(default_factory=ShortDerivationConfig)


def _vb_cfg(global_cfg: dict[str, Any], pipeline: dict[str, Any]) -> dict[str, Any]:
    vb = pipeline.get("visual_beats") or global_cfg.get("pipeline", {}).get("visual_beats", {})
    return vb if isinstance(vb, dict) else {}


def _ml_cfg(global_cfg: dict[str, Any], channel_overrides: dict[str, Any]) -> dict[str, Any]:
    ml = channel_overrides.get("media_library") or global_cfg.get("media_library", {})
    return ml if isinstance(ml, dict) else {}


def _sd_cfg(global_cfg: dict[str, Any], channel_overrides: dict[str, Any]) -> dict[str, Any]:
    sd = channel_overrides.get("production") or global_cfg.get("production", {})
    return sd if isinstance(sd, dict) else {}


def _resolve_short_derivation(channel_overrides: dict[str, Any]) -> ShortDerivationConfig:
    global_cfg = load_agent_config()
    merged = {**_sd_cfg(global_cfg, {}), **_sd_cfg(global_cfg, channel_overrides)}
    strategy = str(merged.get("short_derivation_strategy", "hybrid"))
    if strategy not in ("crop", "native", "hybrid"):
        strategy = "hybrid"
    mode = str(merged.get("short_derivation_mode", "free_sources_only"))
    if mode not in ("reuse_pool_only", "free_sources_only", "full"):
        mode = "free_sources_only"
    return ShortDerivationConfig(
        strategy=strategy,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        hybrid_teaser_max_clips=int(merged.get("hybrid_teaser_max_clips", 2)),
    )


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
        voice=str(gemini.get("voice", "Leda")),
        language_code=str(gemini.get("language_code", "fr")),
    )


def _normalize_tts_engine(raw: str) -> TtsEngine:
    engine = str(raw or "azure").strip().lower()
    if engine in ("azure", "gemini", "edge-tts"):
        return engine  # type: ignore[return-value]
    return "azure"


def _parse_tts_format_profile(raw: dict[str, Any] | None, *, fallback_engine: str, fallback_voice: str) -> TtsFormatProfile:
    if not isinstance(raw, dict):
        return TtsFormatProfile(engine=_normalize_tts_engine(fallback_engine), voice=fallback_voice)
    engine = _normalize_tts_engine(str(raw.get("engine", fallback_engine)))
    voice = str(raw.get("voice", fallback_voice))
    return TtsFormatProfile(engine=engine, voice=voice)


def _resolve_tts_format_profiles(
    tts: dict[str, Any],
    gemini_tts: GeminiTtsConfig,
) -> tuple[TtsFormatProfile, TtsFormatProfile]:
    """Profils voix short/long — compat legacy engine/voice + gemini.apply_to."""
    default_engine = str(tts.get("engine", "azure"))
    default_voice = str(tts.get("voice", "fr-FR-Vivienne:DragonHDLatestNeural"))
    gemini_profile = TtsFormatProfile(engine="gemini", voice=gemini_tts.voice)
    default_profile = TtsFormatProfile(
        engine=_normalize_tts_engine(default_engine),
        voice=default_voice,
    )

    short_raw = tts.get("short")
    long_raw = tts.get("long")
    if isinstance(short_raw, dict) or isinstance(long_raw, dict):
        return (
            _parse_tts_format_profile(
                short_raw if isinstance(short_raw, dict) else None,
                fallback_engine=default_engine,
                fallback_voice=default_voice,
            ),
            _parse_tts_format_profile(
                long_raw if isinstance(long_raw, dict) else None,
                fallback_engine=default_engine,
                fallback_voice=default_voice,
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


def tts_profile_for_channel(cfg: ChannelRuntimeConfig, *, is_short: bool) -> TtsFormatProfile:
    return cfg.tts_short if is_short else cfg.tts_long


def _resolve_audio_mastering(
    global_cfg: dict[str, Any], channel_overrides: dict[str, Any]
) -> AudioMasteringConfig:
    base = global_cfg.get("audio_mastering", {})
    override = channel_overrides.get("audio_mastering", {})
    base = base if isinstance(base, dict) else {}
    override = override if isinstance(override, dict) else {}
    merged: dict[str, Any] = {**base, **override}
    if base.get("compressor") or override.get("compressor"):
        merged["compressor"] = {
            **(base.get("compressor") or {}),
            **(override.get("compressor") or {}),
        }
    try:
        return AudioMasteringConfig(**merged)
    except Exception:  # config invalide → preset par défaut
        logger.warning("Config audio_mastering invalide — preset par défaut utilisé")
        return AudioMasteringConfig()


def _resolve_subtitles(channel_overrides: dict[str, Any]) -> SubtitleConfig:
    global_cfg = load_agent_config().get("subtitles", {})
    channel_subs = channel_overrides.get("subtitles", {})
    if not isinstance(channel_subs, dict):
        channel_subs = {}
    merged = {**global_cfg, **channel_subs}
    return SubtitleConfig(
        enabled=bool(merged.get("enabled", True)),
        style="karaoke",
        max_words_per_line=int(merged.get("max_words_per_line", 3)),
        pause_threshold_ms=int(merged.get("pause_threshold_ms", 400)),
        font_name=str(merged.get("font_name", "DejaVu Sans")),
        font_size=int(merged.get("font_size", 68)),
        primary_color=str(merged.get("primary_color", "#FFFFFF")),
        highlight_color=str(merged.get("highlight_color", "#FFE600")),
        outline_color=str(merged.get("outline_color", "#000000")),
        outline_width=int(merged.get("outline_width", 4)),
        vertical_position=float(merged.get("vertical_position", 0.65)),
        margin_v=int(merged.get("margin_v", 120)),
        play_res_x=int(merged.get("play_res_x", 1080)),
        play_res_y=int(merged.get("play_res_y", 1920)),
        active_word_scale=int(merged.get("active_word_scale", 115)),
        uppercase_highlight=bool(merged.get("uppercase_highlight", True)),
        uppercase_word_scale=int(merged.get("uppercase_word_scale", 120)),
    )


def _resolve_runway(channel_overrides: dict[str, Any]) -> RunwayConfig:
    global_cfg = load_agent_config().get("runway", {})
    channel_runway = channel_overrides.get("runway", {})
    if not isinstance(channel_runway, dict):
        channel_runway = {}
    merged = {**global_cfg, **channel_runway}
    duration = int(merged.get("default_duration_s", 5))
    if duration not in (5, 10):
        duration = 5
    return RunwayConfig(
        enabled=bool(merged.get("enabled", False)),
        monthly_budget_usd=float(merged.get("monthly_budget_usd", 20.0)),
        cost_per_second_usd=float(merged.get("cost_per_second_usd", 0.05)),
        default_duration_s=duration,  # type: ignore[arg-type]
        model=str(merged.get("model", "gen4_turbo")),
        resolution=str(merged.get("resolution", "1280:720")),
        max_clips_per_video=int(merged.get("max_clips_per_video", 3)),
        max_clips_per_short=int(merged.get("max_clips_per_short", 1)),
    )


def _resolve_ai_fallback(channel_overrides: dict[str, Any]) -> AiFallbackConfig:
    global_cfg = load_agent_config().get("media_sources", {}).get("ai_fallback", {})
    media_channel = channel_overrides.get("media_sources", {})
    ai_channel = media_channel.get("ai_fallback", {}) if isinstance(media_channel, dict) else {}

    raw_plan = str(ai_channel.get("plan", global_cfg.get("default_plan", "flux_pro")))
    normalized_plan = PLAN_LEGACY_ALIASES.get(raw_plan, raw_plan)
    try:
        plan = AiImagePlan(normalized_plan)
    except ValueError:
        plan = AiImagePlan.FLUX_PRO

    fallback_chain = ai_channel.get("fallback_chain") or global_cfg.get(
        "default_fallback_chain", ["imagen3"]
    )
    return AiFallbackConfig(
        enabled=bool(ai_channel.get("enabled", global_cfg.get("enabled", True))),
        plan=plan,
        fallback_chain=[str(x) for x in fallback_chain],
        max_images_per_segment=int(
            ai_channel.get("max_images_per_segment", global_cfg.get("max_images_per_segment", 2))
        ),
        max_ai_images_per_video=int(
            ai_channel.get(
                "max_ai_images_per_video",
                global_cfg.get("max_ai_images_per_video", 10),
            )
        ),
        max_ai_images_per_week=(
            int(ai_channel["max_ai_images_per_week"])
            if ai_channel.get("max_ai_images_per_week") is not None
            else global_cfg.get("max_ai_images_per_week")
        ),
        fallback_rate_override=(
            float(ai_channel["fallback_rate_override"])
            if ai_channel.get("fallback_rate_override") is not None
            else None
        ),
    )


def _priority_for_category(theme_category: str, overrides: dict[str, Any]) -> list[str]:
    ms = overrides.get("media_sources", {})
    if isinstance(ms, dict) and ms.get("priority"):
        return [str(s) for s in ms["priority"]]
    if "media_source_priority" in overrides:
        raw = overrides["media_source_priority"]
        if isinstance(raw, list):
            return [str(s) for s in raw]
    category = theme_category.lower()
    for key, sources in THEME_SOURCE_PRIORITY.items():
        if key in category:
            return sources
    global_cfg = load_agent_config().get("media_sources", {}).get("priority_by_theme", {})
    if category in global_cfg:
        return global_cfg[category]
    if "default" in global_cfg:
        return global_cfg["default"]
    return THEME_SOURCE_PRIORITY.get(category, THEME_SOURCE_PRIORITY["default"])


def _tags_from_channel(channel: Channel) -> list[str]:
    if channel.config and channel.config.get("publishing", {}).get("default_tags"):
        return list(channel.config["publishing"]["default_tags"])
    if channel.brand_kit and channel.brand_kit.get("default_tags"):
        return [str(t) for t in channel.brand_kit["default_tags"]]
    return []


def resolve_channel_config(
    channel: Channel,
    *,
    subscription_limits: "SubscriptionLimits | None" = None,
) -> ChannelRuntimeConfig:
    """Fusionne agent_config.json global et channel.config (surcharges)."""
    from agent.core.subscription import SubscriptionLimits, apply_subscription_caps

    global_cfg = load_agent_config()
    channel_overrides: dict[str, Any] = dict(channel.config or {})
    if subscription_limits is not None:
        channel_overrides = apply_subscription_caps(channel_overrides, subscription_limits)
    if channel.brand_kit:
        if channel.brand_kit.get("media_source_priority") and "media_source_priority" not in channel_overrides:
            channel_overrides["media_source_priority"] = channel.brand_kit["media_source_priority"]
        if channel.brand_kit.get("default_tags") and not channel_overrides.get("publishing", {}).get("default_tags"):
            channel_overrides.setdefault("publishing", {})["default_tags"] = channel.brand_kit["default_tags"]

    pipeline = {**global_cfg.get("pipeline", {}), **channel_overrides.get("pipeline", {})}
    tts = {**global_cfg.get("tts", {}), **channel_overrides.get("tts", {})}
    tts_voice = str(tts.get("voice", "fr-FR-Vivienne:DragonHDLatestNeural"))
    content_language = _resolve_content_language(channel_overrides, global_cfg, tts_voice)
    publishing = {**global_cfg.get("publishing", {}), **channel_overrides.get("publishing", {})}
    engagement = {**global_cfg.get("engagement", {}), **channel_overrides.get("engagement", {})}
    production = channel_overrides.get("production", {})
    editorial = channel_overrides.get("editorial", {})
    media_global = global_cfg.get("media_sources", {})
    media_channel = channel_overrides.get("media_sources", {})

    default_tags = list(publishing.get("default_tags", [])) or _tags_from_channel(channel)
    raw_quotas = publishing.get("daily_quotas", {})
    daily_quotas = DailyQuotasConfig(
        long=int(raw_quotas.get("long", 1)),
        short=int(raw_quotas.get("short", 3)),
    )
    platform_slots = dict(publishing.get("platform_slots", {}))
    enabled_platforms = list(publishing.get("enabled_platforms", DEFAULT_PLATFORMS))

    production_mode = str(production.get("mode", "mixed"))
    if production_mode not in ("mixed", "long_only", "shorts_only"):
        production_mode = "mixed"

    if production_mode == "long_only":
        daily_quotas = DailyQuotasConfig(long=daily_quotas.long, short=0)
    elif production_mode == "shorts_only":
        daily_quotas = DailyQuotasConfig(long=0, short=daily_quotas.short or 3)

    media_sources = MediaSourcesConfig(
        priority=_priority_for_category(channel.theme_category, channel_overrides),
        min_candidates_per_segment=int(
            media_channel.get("min_candidates_per_segment", pipeline.get("images_per_segment", 4))
        ),
        enable_ai_fallback=bool(media_channel.get("enable_ai_fallback", True)),
        images_per_segment=int(pipeline.get("images_per_segment", media_global.get("images_per_segment", 4))),
        prefer_video=bool(media_channel.get("prefer_video", media_global.get("prefer_video", True))),
        video_clips_per_segment=int(
            media_channel.get(
                "video_clips_per_segment",
                media_global.get("video_clips_per_segment", 1),
            )
        ),
        min_width_px=int(media_global.get("min_width_px", 1280)),
        relevance_min_score=int(media_global.get("relevance_min_score", 60)),
        max_search_iterations=int(media_global.get("max_search_iterations", 3)),
        min_passing_candidates_multiplier=float(
            media_global.get("min_passing_candidates_multiplier", 1.5)
        ),
        relevance_min_score_high_precision=int(
            media_global.get("relevance_min_score_high_precision", 75)
        ),
        niche_threshold_candidates=int(media_global.get("niche_threshold_candidates", 2)),
        enable_post_selection_audit=bool(
            media_global.get("enable_post_selection_audit", True)
        ),
        forced_best_min_score=int(media_global.get("forced_best_min_score", 40)),
    )

    gemini_tts = _resolve_gemini_tts(tts)
    tts_short, tts_long = _resolve_tts_format_profiles(tts, gemini_tts)

    kit = channel.brand_kit or {}
    return ChannelRuntimeConfig(
        media_source_priority=media_sources.priority,
        media_sources=media_sources,
        tts_engine=str(tts.get("engine", "azure")),
        tts_voice=str(tts.get("voice", "fr-FR-Vivienne:DragonHDLatestNeural")),
        tts_fallback_voice=str(tts.get("fallback_voice", "fr-FR-DeniseNeural")),
        tts_style=str(tts.get("style", tts.get("default_style", "narration-relaxed"))),
        tts_rate=str(tts.get("rate", tts.get("default_rate", "+0%"))),
        tts_pitch=str(tts.get("pitch", "+0Hz")),
        tts_insert_pauses=bool(tts.get("insert_pauses", True)),
        tts_comma_pauses=bool(tts.get("comma_pauses", False)),
        tts_oralize=bool(tts.get("oralize", True)),
        audio_mastering=_resolve_audio_mastering(global_cfg, channel_overrides),
        gemini_tts=gemini_tts,
        tts_short=tts_short,
        tts_long=tts_long,
        default_tags=default_tags,
        youtube_category_id=str(publishing.get("youtube_category_id", "27")),
        auto_publish=bool(publishing.get("auto_publish", False)),
        timezone=str(publishing.get("timezone", "Europe/Paris")),
        daily_quotas=daily_quotas,
        platform_slots=platform_slots,
        enabled_platforms=enabled_platforms,
        production_mode=production_mode,  # type: ignore[arg-type]
        short_duration_s=int(production.get("short_duration_s", global_cfg.get("content_planning", {}).get("default_short_duration_s", 60))),
        min_short_duration_s=int(
            production.get(
                "min_short_duration_s",
                global_cfg.get("content_planning", {}).get("min_short_duration_s", 60),
            )
        ),
        max_short_duration_s=int(
            production.get(
                "max_short_duration_s",
                global_cfg.get("content_planning", {}).get(
                    "max_short_duration_s",
                    global_cfg.get("video", {}).get("short", {}).get("max_duration_tiktok", 120),
                ),
            )
        ),
        min_duration_tiktok=int(
            global_cfg.get("video", {}).get("short", {}).get("min_duration_tiktok", 60)
        ),
        editorial_tone=str(editorial.get("tone", "")),
        editorial_target_audience=str(editorial.get("target_audience", "Grand public curieux, français")),
        editorial_differentiator=str(editorial.get("differentiator", kit.get("content_angle", ""))),
        editorial_formats=resolve_editorial_formats(channel_overrides),
        format_rotation=resolve_format_rotation_config(channel_overrides),
        creative_brief=str(getattr(channel, "creative_brief", "") or ""),
        min_critic_score=int(pipeline.get("min_critic_score", global_cfg.get("pipeline", {}).get("min_critic_score", 90))),
        min_short_structure_score=int(
            pipeline.get(
                "min_short_structure_score",
                global_cfg.get("pipeline", {}).get("min_short_structure_score", 15),
            )
        ),
        max_critic_iterations=int(
            pipeline.get("max_critic_iterations", global_cfg.get("pipeline", {}).get("max_critic_iterations", 3))
        ),
        max_fact_check_iterations=int(
            pipeline.get(
                "max_fact_check_iterations",
                global_cfg.get("pipeline", {}).get("max_fact_check_iterations", 3),
            )
        ),
        min_image_duration_s=int(
            pipeline.get("min_image_duration_s", global_cfg.get("pipeline", {}).get("min_image_duration_s", 4))
        ),
        min_image_duration_short_s=int(
            pipeline.get(
                "min_image_duration_short_s",
                global_cfg.get("pipeline", {}).get("min_image_duration_short_s", 1.5),
            )
        ),
        max_static_shot_s=int(
            pipeline.get(
                "max_static_shot_s",
                global_cfg.get("pipeline", {}).get("max_static_shot_s", 8),
            )
        ),
        content_language=content_language,
        visual_beats=VisualBeatsConfig(
            enabled=bool(_vb_cfg(global_cfg, pipeline).get("enabled", True)),
            min_beats_per_short_segment=int(
                _vb_cfg(global_cfg, pipeline).get("min_beats_per_short_segment", 3)
            ),
            max_beats_per_segment=int(
                _vb_cfg(global_cfg, pipeline).get("max_beats_per_segment", 8)
            ),
            min_diagram_duration_s=float(
                _vb_cfg(global_cfg, pipeline).get("min_diagram_duration_s", 6.0)
            ),
            min_diagram_duration_short_s=float(
                _vb_cfg(global_cfg, pipeline).get("min_diagram_duration_short_s", 4.0)
            ),
        ),
        media_library=MediaLibraryConfig(
            enabled=bool(_ml_cfg(global_cfg, channel_overrides).get("enabled", True)),
            pool_min_score=int(_ml_cfg(global_cfg, channel_overrides).get("pool_min_score", 70)),
            reuse_min_score=int(_ml_cfg(global_cfg, channel_overrides).get("reuse_min_score", 80)),
            max_pool_size_per_project=int(
                _ml_cfg(global_cfg, channel_overrides).get("max_pool_size_per_project", 100)
            ),
            scope=str(_ml_cfg(global_cfg, channel_overrides).get("scope", "project")),
        ),
        short_derivation=_resolve_short_derivation(channel_overrides),
        auto_reply_comments=bool(engagement.get("auto_reply_comments", True)),
        max_replies_per_run=int(engagement.get("max_replies_per_run", 10)),
        max_comments_fetched=int(engagement.get("max_comments_fetched", 50)),
        reply_llm_screen=bool(engagement.get("reply_llm_screen", True)),
        require_reply_review=bool(engagement.get("require_reply_review", False)),
        analytics_enabled=bool(engagement.get("analytics_enabled", True)),
        comments_enabled=bool(engagement.get("comments_enabled", True)),
        max_publications_per_engagement_run=int(
            engagement.get(
                "max_publications_per_engagement_run",
                global_cfg.get("llm", {}).get("max_publications_per_engagement_run", 40),
            )
        ),
        ai_fallback=_resolve_ai_fallback(channel_overrides),
        runway=_resolve_runway(channel_overrides),
        subtitles=_resolve_subtitles(channel_overrides),
    )
