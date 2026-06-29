from __future__ import annotations

import asyncio
import logging
import statistics
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent.core.config import load_agent_config
from agent.skills.video.gemini_video_io import analyze_video_json_with_gemini
from agent.skills.video.montage_decisions import load_transition_config, validate_transition

logger = logging.getLogger(__name__)

BEAT_SLOT_MIN = 1.5
BEAT_SLOT_MAX = 5.0
ZOOM_FACTOR_MIN = 0.02
ZOOM_FACTOR_MAX = 0.12
TRANSITION_DURATION_MIN = 0.15
TRANSITION_DURATION_MAX = 0.6
MAX_CUES_MIN = 4
MAX_CUES_MAX = 20
FLASH_DURATION_MIN = 0.08
FLASH_DURATION_MAX = 0.3

STYLE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "required": [
        "avg_shot_duration_s",
        "shot_duration_std_s",
        "dominant_transitions",
        "avg_transition_duration_s",
        "pattern_interrupts_per_min",
        "caption_style",
        "caption_words_per_line",
        "hook_duration_s",
        "hook_transition_style",
        "ken_burns_intensity",
        "pan_frequency",
        "is_short_format",
        "inter_segment_flash_detected",
    ],
    "properties": {
        "avg_shot_duration_s": {"type": "NUMBER"},
        "shot_duration_std_s": {"type": "NUMBER"},
        "dominant_transitions": {"type": "ARRAY", "items": {"type": "STRING"}},
        "avg_transition_duration_s": {"type": "NUMBER"},
        "pattern_interrupts_per_min": {"type": "NUMBER"},
        "caption_style": {"type": "STRING"},
        "caption_words_per_line": {"type": "INTEGER"},
        "hook_duration_s": {"type": "NUMBER"},
        "hook_transition_style": {"type": "STRING"},
        "ken_burns_intensity": {"type": "NUMBER"},
        "pan_frequency": {"type": "NUMBER"},
        "is_short_format": {"type": "BOOLEAN"},
        "inter_segment_flash_detected": {"type": "BOOLEAN"},
    },
}

STYLE_EXTRACTION_PROMPT = """Analyse la GRAMMAIRE DE MONTAGE de cette vidéo éducative (pas la qualité du contenu).

Mesure uniquement des paramètres numériques et des choix techniques observables :
- Durée moyenne des plans (secondes) et variance de pacing
- Types de transitions dominants (fade, dissolve, wipeleft, pixelize, fadewhite, etc.)
- Durée moyenne des transitions
- Fréquence des pattern-interrupts par minute (whoosh, flash, zoom punch, glitch)
- Style de sous-titres : karaoke (mot surligné), minimal (texte simple), none
- Mots par ligne de sous-titre en moyenne
- Durée du hook initial (secondes) et style de transition du hook
- Intensité Ken Burns / zoom sur photos (0.0 = statique, 1.0 = très dynamique)
- Fréquence de panoramiques (0.0 à 1.0)
- Format court vertical (short < 120s, ratio 9:16) vs long 16:9
- Flash blanc entre chapitres/sections détecté (true/false)

Retourne UNIQUEMENT le JSON structuré demandé, sans markdown."""


class EditGrammar(BaseModel):
    avg_shot_duration_s: float = 2.5
    shot_duration_std_s: float = 0.5
    dominant_transitions: list[str] = Field(default_factory=lambda: ["fade"])
    avg_transition_duration_s: float = 0.35
    pattern_interrupts_per_min: float = 8.0
    caption_style: Literal["karaoke", "minimal", "none"] = "karaoke"
    caption_words_per_line: int = 3
    hook_duration_s: float = 15.0
    hook_transition_style: str = "fadewhite"
    ken_burns_intensity: float = 0.5
    pan_frequency: float = 0.3
    is_short_format: bool = False
    inter_segment_flash_detected: bool = False

    @classmethod
    def from_gemini_data(cls, data: dict[str, Any]) -> EditGrammar:
        caption_raw = str(data.get("caption_style", "karaoke")).lower().strip()
        if caption_raw not in ("karaoke", "minimal", "none"):
            caption_raw = "karaoke"
        transitions = [
            str(t).strip().lower()
            for t in (data.get("dominant_transitions") or [])
            if str(t).strip()
        ]
        return cls(
            avg_shot_duration_s=float(data.get("avg_shot_duration_s", 2.5)),
            shot_duration_std_s=float(data.get("shot_duration_std_s", 0.5)),
            dominant_transitions=transitions or ["fade"],
            avg_transition_duration_s=float(data.get("avg_transition_duration_s", 0.35)),
            pattern_interrupts_per_min=float(data.get("pattern_interrupts_per_min", 8.0)),
            caption_style=caption_raw,  # type: ignore[arg-type]
            caption_words_per_line=int(data.get("caption_words_per_line", 3)),
            hook_duration_s=float(data.get("hook_duration_s", 15.0)),
            hook_transition_style=str(data.get("hook_transition_style", "fadewhite")),
            ken_burns_intensity=float(data.get("ken_burns_intensity", 0.5)),
            pan_frequency=float(data.get("pan_frequency", 0.3)),
            is_short_format=bool(data.get("is_short_format", False)),
            inter_segment_flash_detected=bool(data.get("inter_segment_flash_detected", False)),
        )


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _median(values: list[float], default: float) -> float:
    return float(statistics.median(values)) if values else default


def _mode_str(values: list[str], default: str) -> str:
    if not values:
        return default
    return Counter(values).most_common(1)[0][0]


def aggregate_edit_grammars(grammars: list[EditGrammar]) -> EditGrammar:
    if not grammars:
        return EditGrammar()
    if len(grammars) == 1:
        return grammars[0]

    all_transitions: list[str] = []
    for g in grammars:
        all_transitions.extend(g.dominant_transitions)

    caption_styles = [g.caption_style for g in grammars]
    hook_transitions = [g.hook_transition_style for g in grammars]

    return EditGrammar(
        avg_shot_duration_s=_median([g.avg_shot_duration_s for g in grammars], 2.5),
        shot_duration_std_s=_median([g.shot_duration_std_s for g in grammars], 0.5),
        dominant_transitions=list(dict.fromkeys(all_transitions))[:5] or ["fade"],
        avg_transition_duration_s=_median([g.avg_transition_duration_s for g in grammars], 0.35),
        pattern_interrupts_per_min=_median([g.pattern_interrupts_per_min for g in grammars], 8.0),
        caption_style=_mode_str(caption_styles, "karaoke"),  # type: ignore[arg-type]
        caption_words_per_line=int(round(_median([float(g.caption_words_per_line) for g in grammars], 3))),
        hook_duration_s=_median([g.hook_duration_s for g in grammars], 15.0),
        hook_transition_style=_mode_str(hook_transitions, "fadewhite"),
        ken_burns_intensity=_median([g.ken_burns_intensity for g in grammars], 0.5),
        pan_frequency=_median([g.pan_frequency for g in grammars], 0.3),
        is_short_format=sum(1 for g in grammars if g.is_short_format) > len(grammars) / 2,
        inter_segment_flash_detected=sum(1 for g in grammars if g.inter_segment_flash_detected)
        > len(grammars) / 2,
    )


def _validated_transition(name: str, *, is_short: bool) -> str:
    cfg = load_transition_config(is_short=is_short)
    return validate_transition(name, cfg)


def _zoom_from_intensity(intensity: float) -> float:
    raw = ZOOM_FACTOR_MIN + intensity * (ZOOM_FACTOR_MAX - ZOOM_FACTOR_MIN)
    return clamp(raw, ZOOM_FACTOR_MIN, ZOOM_FACTOR_MAX)


def _mood_transitions_from_dominant(
    dominant: list[str],
    *,
    is_short: bool,
) -> dict[str, str]:
    cfg = load_transition_config(is_short=is_short)
    moods = list(cfg.mood_defaults.keys()) or [
        "energique",
        "dramatique",
        "tension",
        "humoristique",
        "calme",
    ]
    validated = [_validated_transition(t, is_short=is_short) for t in dominant]
    if not validated:
        validated = ["fade"]
    result: dict[str, str] = {}
    for i, mood in enumerate(moods):
        result[mood] = validated[i % len(validated)]
    return result


def edit_grammar_to_montage_profile(
    short_grammar: EditGrammar | None,
    long_grammar: EditGrammar | None,
    *,
    reference_count: int = 0,
) -> dict[str, Any]:
    """Mappe une ou deux grammaires (short/long) vers channel.config.montage_profile."""
    profile: dict[str, Any] = {
        "meta": {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "reference_count": reference_count,
            "source": "style_extractor_v1",
        },
    }

    if short_grammar is not None:
        beat_slot = clamp(short_grammar.avg_shot_duration_s, BEAT_SLOT_MIN, BEAT_SLOT_MAX)
        trans_dur = clamp(
            short_grammar.avg_transition_duration_s,
            TRANSITION_DURATION_MIN,
            TRANSITION_DURATION_MAX,
        )
        max_cues = int(
            round(clamp(short_grammar.pattern_interrupts_per_min, MAX_CUES_MIN, MAX_CUES_MAX))
        )
        dominant = short_grammar.dominant_transitions[:3]
        profile["short_montage_profile"] = {
            "beat_slot_s": beat_slot,
            "ken_burns": {
                "zoom_factor": _zoom_from_intensity(short_grammar.ken_burns_intensity),
                "pan_enabled": short_grammar.pan_frequency >= 0.4,
            },
            "transitions": {
                "duration_s": trans_dur,
                "mood_defaults": _mood_transitions_from_dominant(dominant, is_short=True),
            },
            "sfx": {
                "beat_cuts_enabled": max_cues >= 6,
                "max_cues_per_minute": max_cues,
            },
        }

    if long_grammar is not None:
        trans_dur = clamp(
            long_grammar.avg_transition_duration_s,
            TRANSITION_DURATION_MIN,
            TRANSITION_DURATION_MAX,
        )
        max_cues = int(
            round(clamp(long_grammar.pattern_interrupts_per_min, MAX_CUES_MIN, MAX_CUES_MAX))
        )
        hook_trans = _validated_transition(long_grammar.hook_transition_style, is_short=False)
        dominant = long_grammar.dominant_transitions[:3]
        flash_dur = clamp(
            long_grammar.avg_transition_duration_s * 0.4,
            FLASH_DURATION_MIN,
            FLASH_DURATION_MAX,
        )
        profile["long_montage_profile"] = {
            "sfx": {
                "beat_cuts_enabled": max_cues >= 5,
                "max_cues_per_minute": max_cues,
                "text_pop_enabled": long_grammar.caption_style == "karaoke",
            },
            "inter_segment_flash": long_grammar.inter_segment_flash_detected,
            "inter_segment_flash_duration_s": flash_dur,
            "pacing": {
                "hook_transition": hook_trans,
                "mood_transitions": _mood_transitions_from_dominant(dominant, is_short=False),
            },
        }
        profile["long_montage_profile"]["transitions"] = {"duration_s": trans_dur}

    return profile


def load_style_config() -> dict[str, Any]:
    return dict(load_agent_config().get("style") or {})


def _download_video_sync(url: str, dest_dir: Path, *, max_clip_s: int) -> Path | None:
    try:
        import yt_dlp
    except ImportError:
        logger.error("yt-dlp non installé")
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(dest_dir / "%(id)s.%(ext)s")

    opts: dict[str, Any] = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "download_sections": f"*0-{max_clip_s}",
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None
            vid_id = info.get("id", "video")
            for ext in ("mp4", "mkv", "webm"):
                candidate = dest_dir / f"{vid_id}.{ext}"
                if candidate.is_file():
                    return candidate
            requested = info.get("requested_downloads") or []
            for item in requested:
                fp = item.get("filepath")
                if fp and Path(fp).is_file():
                    return Path(fp)
    except Exception as exc:
        logger.warning("yt-dlp échoué pour %s : %s", url, exc)
    return None


async def download_reference_video(url: str, *, max_clip_s: int | None = None) -> Path | None:
    cfg = load_style_config()
    clip_s = max_clip_s if max_clip_s is not None else int(cfg.get("max_clip_duration_s", 180))
    dest = Path(f"./tmp/style_refs/{uuid.uuid4()}")
    return await asyncio.to_thread(_download_video_sync, url, dest, max_clip_s=clip_s)


async def analyze_path_edit_grammar(
    video_path: Path,
    *,
    api_key: str,
    model_name: str = "gemini-2.5-pro",
) -> EditGrammar | None:
    if not video_path.is_file():
        logger.warning("StyleExtractor : fichier introuvable %s", video_path)
        return None
    try:
        data = await analyze_video_json_with_gemini(
            video_path,
            STYLE_EXTRACTION_PROMPT,
            api_key=api_key,
            response_schema=STYLE_RESPONSE_SCHEMA,
            model_name=model_name,
            label="style_extractor",
        )
        return EditGrammar.from_gemini_data(data)
    except Exception as exc:
        logger.warning("StyleExtractor Gemini échoué pour %s : %s", video_path, exc)
        return None


async def extract_edit_grammar_from_paths(
    paths: list[Path],
    *,
    api_key: str,
    model_name: str = "gemini-2.5-pro",
) -> tuple[EditGrammar | None, EditGrammar | None]:
    """Analyse des fichiers locaux ; retourne (short_aggregate, long_aggregate)."""
    short_grams: list[EditGrammar] = []
    long_grams: list[EditGrammar] = []

    for path in paths:
        grammar = await analyze_path_edit_grammar(path, api_key=api_key, model_name=model_name)
        if grammar is None:
            continue
        if grammar.is_short_format:
            short_grams.append(grammar)
        else:
            long_grams.append(grammar)

    if not short_grams and not long_grams:
        return None, None

    short_agg = aggregate_edit_grammars(short_grams) if short_grams else None
    long_agg = aggregate_edit_grammars(long_grams) if long_grams else None
    return short_agg, long_agg


async def extract_edit_grammar(
    video_urls: list[str],
    *,
    api_key: str,
    max_clip_s: int | None = None,
    model_name: str = "gemini-2.5-pro",
) -> tuple[EditGrammar | None, EditGrammar | None]:
    """Télécharge et analyse les URLs ; retourne grammaires short/long agrégées."""
    paths: list[Path] = []
    cfg = load_style_config()
    clip_s = max_clip_s if max_clip_s is not None else int(cfg.get("max_clip_duration_s", 180))

    for url in video_urls:
        path = await download_reference_video(url, max_clip_s=clip_s)
        if path is not None:
            paths.append(path)

    if not paths:
        return None, None

    return await extract_edit_grammar_from_paths(
        paths, api_key=api_key, model_name=model_name
    )
