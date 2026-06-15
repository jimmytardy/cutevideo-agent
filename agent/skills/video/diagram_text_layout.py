from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from agent.core.json_parse import parse_gemini_response
from agent.core.visual_beats import DiagramLabel, TextOverlayPlacement

logger = logging.getLogger(__name__)

LAYOUT_MODEL = "gemini-2.5-flash"
LAYOUT_FALLBACK = "gemini-2.5-flash-lite"
LAYOUT_MODELS = (LAYOUT_MODEL, LAYOUT_FALLBACK)

LAYOUT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "x_norm": {"type": "number"},
                    "y_norm": {"type": "number"},
                    "fontsize": {"type": "integer"},
                    "box": {"type": "boolean"},
                },
                "required": ["text", "x_norm", "y_norm"],
            },
        },
    },
    "required": ["labels"],
}

LAYOUT_PROMPT = """Tu es un expert en mise en page de schémas éducatifs vidéo.

Analyse l'image fournie et place chaque label texte sur une zone vide pertinente,
près de l'élément visuel correspondant à son rôle sémantique.
Ne masque pas les flèches principales ni le sujet central.

Langue des labels : {language}
Extrait narration : {narration_excerpt}

Labels à placer (texte exact à utiliser) :
{labels_block}

Retourne UNIQUEMENT ce JSON :
{{
  "labels": [
    {{"text": "...", "x_norm": 0.25, "y_norm": 0.45, "fontsize": 32, "box": true}}
  ]
}}

Règles :
- x_norm et y_norm entre 0.0 et 1.0 (position du centre du texte)
- un placement par label demandé, texte identique à la liste
- fontsize entre 24 et 48 selon importance
- box true pour fond semi-transparent
- éviter les chevauchements entre labels"""


def _layout_cache_path(image_path: Path) -> Path:
    return image_path.with_suffix(image_path.suffix + ".layout.json")


def load_cached_layout(image_path: Path) -> list[TextOverlayPlacement] | None:
    cache = _layout_cache_path(image_path)
    if not cache.exists():
        return None
    try:
        raw = json.loads(cache.read_text(encoding="utf-8"))
        labels = raw.get("labels") if isinstance(raw, dict) else raw
        if not isinstance(labels, list):
            return None
        return [_placement_from_dict(item) for item in labels if isinstance(item, dict)]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Cache layout illisible %s : %s", cache, exc)
        return None


def save_layout_cache(image_path: Path, placements: list[TextOverlayPlacement]) -> None:
    cache = _layout_cache_path(image_path)
    payload = {"labels": [p.model_dump() for p in placements]}
    cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _placement_from_dict(item: dict[str, Any]) -> TextOverlayPlacement:
    return TextOverlayPlacement(
        text=str(item.get("text", ""))[:40],
        x_norm=_clamp(float(item.get("x_norm", 0.5))),
        y_norm=_clamp(float(item.get("y_norm", 0.5))),
        fontsize=int(item.get("fontsize", 36)),
        box=bool(item.get("box", True)),
    )


def _clamp(value: float) -> float:
    return max(0.05, min(0.95, value))


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".png",):
        return "image/png"
    if suffix in (".webp",):
        return "image/webp"
    return "image/jpeg"


def _labels_block(labels: list[DiagramLabel]) -> str:
    lines: list[str] = []
    for i, label in enumerate(labels):
        role = label.role or "element"
        lines.append(f'{i + 1}. "{label.text}" (role: {role})')
    return "\n".join(lines)


def fallback_text_layout(
    labels: list[DiagramLabel],
    *,
    vertical: bool = False,
    visual_type: str = "",
) -> list[TextOverlayPlacement]:
    if not labels:
        return []
    if len(labels) == 1 and visual_type in ("quote_card", "statistic_highlight"):
        return [
            TextOverlayPlacement(
                text=labels[0].text,
                x_norm=0.5,
                y_norm=0.5,
                fontsize=48 if not vertical else 42,
                box=True,
            )
        ]
    placements: list[TextOverlayPlacement] = []
    base_y = 0.82 if not vertical else 0.78
    step = 0.08
    for i, label in enumerate(labels):
        placements.append(
            TextOverlayPlacement(
                text=label.text,
                x_norm=0.5,
                y_norm=max(0.1, base_y - i * step),
                fontsize=36 if not vertical else 32,
                box=True,
            )
        )
    return placements


def _resolve_overlaps(placements: list[TextOverlayPlacement], min_dist: float = 0.08) -> list[TextOverlayPlacement]:
    if len(placements) < 2:
        return placements
    adjusted = list(placements)
    for i in range(len(adjusted)):
        for j in range(i + 1, len(adjusted)):
            a, b = adjusted[i], adjusted[j]
            dx = a.x_norm - b.x_norm
            dy = a.y_norm - b.y_norm
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < min_dist:
                adjusted[j] = TextOverlayPlacement(
                    text=b.text,
                    x_norm=_clamp(b.x_norm + min_dist),
                    y_norm=_clamp(b.y_norm),
                    fontsize=b.fontsize,
                    box=b.box,
                )
    return adjusted


async def analyze_diagram_text_layout(
    image_path: Path,
    labels: list[DiagramLabel],
    *,
    narration_excerpt: str = "",
    language: str = "fr",
    visual_type: str = "",
    vertical: bool = False,
    width: int = 1920,
    height: int = 1080,
    api_key: str | None = None,
) -> list[TextOverlayPlacement]:
    if not labels:
        return []

    cached = load_cached_layout(image_path)
    if cached and len(cached) >= len(labels):
        return cached[: len(labels)]

    if not api_key:
        logger.warning("Clé Gemini absente — fallback layout fixe")
        return fallback_text_layout(labels, vertical=vertical, visual_type=visual_type)

    try:
        placements = await asyncio.to_thread(
            _analyze_sync,
            image_path,
            labels,
            narration_excerpt,
            language,
            api_key,
        )
        if placements:
            placements = _resolve_overlaps(placements)
            save_layout_cache(image_path, placements)
            return placements
    except Exception as exc:
        logger.warning("Analyse layout Gemini échouée : %s", exc)

    return fallback_text_layout(labels, vertical=vertical, visual_type=visual_type)


def _analyze_sync(
    image_path: Path,
    labels: list[DiagramLabel],
    narration_excerpt: str,
    language: str,
    api_key: str,
) -> list[TextOverlayPlacement]:
    from google import genai
    from google.genai import types

    if not image_path.exists():
        raise FileNotFoundError(str(image_path))

    prompt = LAYOUT_PROMPT.format(
        language=language,
        narration_excerpt=(narration_excerpt or "")[:400],
        labels_block=_labels_block(labels),
    )
    contents: list[Any] = [
        prompt,
        types.Part.from_bytes(data=image_path.read_bytes(), mime_type=_mime_for(image_path)),
    ]
    client = genai.Client(api_key=api_key)
    errors: list[str] = []

    for model_name in LAYOUT_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                    response_json_schema=LAYOUT_RESPONSE_SCHEMA,
                ),
            )
            data = parse_gemini_response(response, model_name, required_field="labels")
            raw_labels = data.get("labels", [])
            if not isinstance(raw_labels, list):
                raise ValueError("labels manquant")
            placements = [_placement_from_dict(item) for item in raw_labels if isinstance(item, dict)]
            if len(placements) < len(labels):
                raise ValueError(f"labels incomplets ({len(placements)}/{len(labels)})")
            by_text = {p.text.strip().lower(): p for p in placements}
            ordered: list[TextOverlayPlacement] = []
            for label in labels:
                key = label.text.strip().lower()
                if key in by_text:
                    ordered.append(by_text[key])
                elif ordered:
                    ordered.append(placements[min(len(ordered), len(placements) - 1)])
                else:
                    ordered.append(placements[0])
            return ordered[: len(labels)]
        except Exception as exc:
            errors.append(f"{model_name}: {exc}")
            logger.warning("Layout Gemini %s échoué : %s", model_name, exc)

    raise RuntimeError("; ".join(errors) if errors else "layout Gemini échoué")
