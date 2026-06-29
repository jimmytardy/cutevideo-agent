from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agent.core.llm_retry import retry_transient_sync
from agent.core.montage_plan import ClipMetadata, ClipSegmentMeta

logger = logging.getLogger(__name__)

CLIP_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "required": [
        "motion_score", "useful_duration_s", "static_ratio", "best_segments", "summary",
    ],
    "properties": {
        "motion_score": {"type": "INTEGER"},
        "useful_duration_s": {"type": "NUMBER"},
        "static_ratio": {"type": "NUMBER"},
        "best_segments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "start_s": {"type": "NUMBER"},
                    "end_s": {"type": "NUMBER"},
                    "reason": {"type": "STRING"},
                    "score": {"type": "INTEGER"},
                    "peak_s": {"type": "NUMBER"},
                },
            },
        },
        "summary": {"type": "STRING"},
    },
}

ANALYSIS_PROMPT = """Analyse ce clip vidéo source pour un montage éducatif.

Contexte : {context}
Durée fichier : {duration_s:.1f}s

Évalue :
- motion_score (0-100) : dynamisme visuel
- static_ratio (0-1) : proportion de plans statiques
- useful_duration_s : durée réellement utile sans plan figé prolongé
- best_segments : 1 à 3 fenêtres [start_s, end_s] les plus pertinentes pour illustrer le contexte ;
  pour chaque segment : score (0-100, pertinence pour le contexte) et peak_s (instant le plus fort en secondes)
- summary : une phrase

Retourne UNIQUEMENT le JSON demandé."""


async def analyze_clip_source(
    clip_path: Path,
    *,
    context: str,
    duration_s: float,
    api_key: str,
    model_name: str = "gemini-2.5-flash",
) -> ClipMetadata | None:
    """Analyse un clip source via Gemini File API."""
    if not clip_path.exists() or not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        from agent.agents.video_analyst_agent import _wait_for_active_file
        from agent.core.json_parse import parse_gemini_response
    except ImportError:
        logger.warning("google-genai indisponible pour clip_source_analyzer")
        return None

    prompt = ANALYSIS_PROMPT.format(context=context[:500], duration_s=duration_s)

    def _run() -> dict[str, Any]:
        client = genai.Client(api_key=api_key)
        uploaded = client.files.upload(
            file=str(clip_path),
            config=types.UploadFileConfig(mime_type="video/mp4"),
        )
        uploaded = _wait_for_active_file(client, types, uploaded)
        response = retry_transient_sync(
            lambda: client.models.generate_content(
                model=model_name,
                contents=[uploaded, prompt],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                    response_schema=CLIP_ANALYSIS_SCHEMA,
                ),
            ),
            label=f"clip_source/{model_name}",
        )
        return parse_gemini_response(response, model_name)

    try:
        import asyncio

        data = await asyncio.to_thread(_run)
    except Exception as exc:
        logger.warning("Analyse clip source échouée %s : %s", clip_path, exc)
        return None

    segments = [
        ClipSegmentMeta(
            start_s=float(s.get("start_s", 0)),
            end_s=float(s.get("end_s", 0)),
            reason=str(s.get("reason", "")),
            score=int(s.get("score", 0) or 0),
            peak_s=float(s["peak_s"]) if s.get("peak_s") is not None else None,
        )
        for s in (data.get("best_segments") or [])
        if isinstance(s, dict)
    ]
    return ClipMetadata(
        motion_score=int(data.get("motion_score", 50)),
        useful_duration_s=float(data.get("useful_duration_s") or duration_s),
        static_ratio=float(data.get("static_ratio", 0.5)),
        best_segments=segments,
        summary=str(data.get("summary", "")),
    )


def clip_metadata_from_dict(raw: dict[str, Any] | None) -> ClipMetadata | None:
    if not raw:
        return None
    try:
        return ClipMetadata.model_validate(raw)
    except Exception:
        return None


def clip_metadata_to_dict(meta: ClipMetadata) -> dict[str, Any]:
    return meta.model_dump(mode="json")
