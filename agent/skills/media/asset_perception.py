from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from agent.core.config import load_agent_config
from agent.core.database import AsyncSessionFactory, MediaAsset
from agent.core.json_parse import parse_gemini_response
from agent.core.llm_retry import retry_transient_sync
from agent.core.montage_plan import ClipMetadata
from agent.skills.media.clip_source_analyzer import (
    analyze_clip_source,
    clip_metadata_from_dict,
    clip_metadata_to_dict,
)

logger = logging.getLogger(__name__)

DEFAULT_PERCEPTION_MODEL = "gemini-2.5-flash"

ASSET_PERCEPTION_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "required": ["salient_box", "composition", "energy"],
    "properties": {
        "salient_box": {
            "type": "ARRAY",
            "items": {"type": "NUMBER"},
        },
        "faces": {"type": "INTEGER"},
        "face_box": {
            "type": "ARRAY",
            "items": {"type": "NUMBER"},
        },
        "horizon_y": {"type": "NUMBER"},
        "composition": {
            "type": "STRING",
            "enum": ["portrait", "wide", "detail", "crowd", "text_heavy", "abstract"],
        },
        "energy": {"type": "INTEGER"},
        "emotional_tone": {"type": "STRING"},
        "dominant_colors": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
    },
}

PERCEPTION_PROMPT = """Analyse cette image pour un montage vidéo éducatif.

Thème : {theme}

Décris le contenu visuel :
- salient_box : zone d'intérêt principale [x, y, w, h] normalisée 0–1 (coin supérieur gauche)
- faces : nombre de visages visibles
- face_box : boîte englobante du visage principal [x, y, w, h] normalisée, ou null
- horizon_y : position verticale de l'horizon (0=haut, 1=bas), null si absent
- composition : portrait | wide | detail | crowd | text_heavy | abstract
- energy : dynamisme visuel 0–100
- emotional_tone : tonalité émotionnelle en quelques mots
- dominant_colors : 2 à 5 couleurs dominantes en hex (#RRGGBB)

Retourne UNIQUEMENT le JSON demandé."""


def load_perception_config() -> dict[str, Any]:
    raw = load_agent_config().get("video", {}).get("perception") or {}
    return raw if isinstance(raw, dict) else {}


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def lookup_perception_by_hash(file_hash: str) -> ClipMetadata | None:
    if not file_hash:
        return None
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MediaAsset.perception)
            .where(
                MediaAsset.file_hash == file_hash,
                MediaAsset.perception.is_not(None),
            )
            .limit(1)
        )
        raw = result.scalar_one_or_none()
    return clip_metadata_from_dict(raw if isinstance(raw, dict) else None)


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def _normalize_box(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        return [max(0.0, min(1.0, float(v))) for v in raw]
    except (TypeError, ValueError):
        return None


def _perception_from_dict(data: dict[str, Any]) -> ClipMetadata:
    composition = data.get("composition")
    if composition not in {
        "portrait", "wide", "detail", "crowd", "text_heavy", "abstract",
    }:
        composition = None
    colors = data.get("dominant_colors") or []
    if not isinstance(colors, list):
        colors = []
    return ClipMetadata(
        salient_box=_normalize_box(data.get("salient_box")),
        faces=int(data.get("faces", 0) or 0),
        face_box=_normalize_box(data.get("face_box")),
        horizon_y=(
            float(data["horizon_y"])
            if data.get("horizon_y") is not None
            else None
        ),
        composition=composition,  # type: ignore[arg-type]
        energy=int(data["energy"]) if data.get("energy") is not None else None,
        emotional_tone=str(data.get("emotional_tone", "")),
        dominant_colors=[str(c) for c in colors if isinstance(c, str)],
    )


def _merge_perception(base: ClipMetadata, spatial: ClipMetadata) -> ClipMetadata:
    merged = base.model_dump()
    spatial_fields = _perception_from_dict(spatial.model_dump()).model_dump(
        exclude_defaults=True,
        exclude={"motion_score", "useful_duration_s", "static_ratio", "best_segments", "summary"},
    )
    merged.update(spatial_fields)
    return ClipMetadata.model_validate(merged)


async def perceive_image(
    path: Path,
    *,
    theme: str,
    api_key: str,
    model_name: str | None = None,
) -> ClipMetadata | None:
    if not path.exists() or not api_key:
        return None
    model = model_name or load_perception_config().get("model") or DEFAULT_PERCEPTION_MODEL
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai indisponible pour asset_perception")
        return None

    prompt = PERCEPTION_PROMPT.format(theme=(theme or "général")[:200])
    image_bytes = path.read_bytes()

    def _run() -> dict[str, Any]:
        client = genai.Client(api_key=api_key)
        contents: list[Any] = [
            prompt,
            types.Part.from_bytes(data=image_bytes, mime_type=_mime_for(path)),
        ]
        response = retry_transient_sync(
            lambda: client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=1024,
                    response_mime_type="application/json",
                    response_schema=ASSET_PERCEPTION_SCHEMA,
                ),
            ),
            label=f"asset_perception/{model}",
        )
        return parse_gemini_response(response, model)

    try:
        data = await asyncio.to_thread(_run)
    except Exception as exc:
        logger.warning("Perception image échouée %s : %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return _perception_from_dict(data)


async def _extract_representative_frame(
    video_path: Path,
    *,
    duration_s: float,
    best_segment_start: float | None = None,
    best_segment_end: float | None = None,
    output_path: Path,
) -> Path | None:
    if best_segment_start is not None and best_segment_end is not None:
        timestamp = best_segment_start + max(0.0, (best_segment_end - best_segment_start) / 2)
    else:
        timestamp = max(0.0, duration_s / 2)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    from agent.skills.video.ffmpeg_runtime import run_ffmpeg

    try:
        await run_ffmpeg(cmd)
    except Exception as exc:
        logger.warning("Extraction frame perception échouée %s : %s", video_path, exc)
        return None
    return output_path if output_path.is_file() else None


async def perceive_asset(
    path: Path,
    *,
    asset_type: str,
    theme: str,
    api_key: str,
    context: str = "",
    duration_s: float | None = None,
    model_name: str | None = None,
) -> tuple[ClipMetadata | None, str | None, bool]:
    """Analyse perceptuelle avec cache par hash fichier.

    Retourne (ClipMetadata, file_hash, cache_hit).
    """
    if not path.is_file():
        return None, None, False

    file_hash = compute_file_hash(path)
    cached = await lookup_perception_by_hash(file_hash)
    if cached is not None:
        logger.info("Perception cache hit hash=%s", file_hash[:12])
        return cached, file_hash, True

    model = model_name or load_perception_config().get("model") or DEFAULT_PERCEPTION_MODEL

    if asset_type == "video":
        from agent.skills.video.ffmpeg_utils import _probe_clip_duration

        try:
            probed_duration = float(duration_s or await _probe_clip_duration(path))
        except Exception:
            probed_duration = duration_s or 0.0
        if probed_duration <= 0:
            return None, file_hash, False

        clip_meta = await analyze_clip_source(
            path,
            context=context[:500],
            duration_s=probed_duration,
            api_key=api_key,
            model_name=model,
        )
        if clip_meta is None:
            return None, file_hash, False

        best_start: float | None = None
        best_end: float | None = None
        if clip_meta.best_segments:
            from agent.skills.video.trim_selector import pick_best_segment

            seg = pick_best_segment(clip_meta.best_segments)
            best_start = seg.start_s
            best_end = seg.end_s

        frame_path = path.with_suffix(path.suffix + ".perception_frame.jpg")
        extracted = await _extract_representative_frame(
            path,
            duration_s=probed_duration,
            best_segment_start=best_start,
            best_segment_end=best_end,
            output_path=frame_path,
        )
        if extracted is None:
            return clip_meta, file_hash, False

        try:
            spatial = await perceive_image(
                extracted,
                theme=theme,
                api_key=api_key,
                model_name=model,
            )
        finally:
            extracted.unlink(missing_ok=True)

        if spatial is None:
            return clip_meta, file_hash, False
        return _merge_perception(clip_meta, spatial), file_hash, False

    spatial = await perceive_image(
        path,
        theme=theme,
        api_key=api_key,
        model_name=model,
    )
    return spatial, file_hash, False


def perception_to_dict(meta: ClipMetadata | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    return clip_metadata_to_dict(meta)
