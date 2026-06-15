from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from agent.core.channel_config import ChannelRuntimeConfig, VisualBeatsConfig

logger = logging.getLogger(__name__)

CUSTOM_VISUAL_TYPE = "custom"


class DiagramLabel(BaseModel):
    text: str = Field(max_length=40)
    role: str = ""


class TextOverlayPlacement(BaseModel):
    text: str
    x_norm: float
    y_norm: float
    fontsize: int = 36
    box: bool = True


class VisualBeat(BaseModel):
    order: int
    phrase_anchor: str
    visual_type: str
    prompt: str
    style_hint: str = ""
    on_screen_text: str = ""
    diagram_labels: list[DiagramLabel] = Field(default_factory=list)
    duration_hint_s: float | None = None

    @field_validator("visual_type")
    @classmethod
    def normalize_visual_type(cls, value: str) -> str:
        from agent.skills.media_sources.ai.prompt_builder import is_known_visual_type

        key = (value or CUSTOM_VISUAL_TYPE).strip().lower().replace(" ", "_")
        if key == CUSTOM_VISUAL_TYPE or is_known_visual_type(key):
            return key
        logger.warning("visual_type inconnu %r — fallback custom", value)
        return CUSTOM_VISUAL_TYPE

    @field_validator("style_hint")
    @classmethod
    def require_style_hint_for_custom(cls, value: str, info: Any) -> str:
        return value

    @model_validator(mode="after")
    def fill_custom_style_hint(self) -> VisualBeat:
        if self.visual_type == CUSTOM_VISUAL_TYPE and not (self.style_hint or "").strip():
            object.__setattr__(self, "style_hint", self.prompt[:200])
        return self

    def resolved_diagram_labels(self) -> list[DiagramLabel]:
        if self.diagram_labels:
            return self.diagram_labels
        text = (self.on_screen_text or "").strip()
        if text:
            return [DiagramLabel(text=text[:40], role="label")]
        return []

    def needs_diagram_labels(self) -> bool:
        from agent.skills.media_sources.ai.prompt_builder import is_diagram_visual_type

        return is_diagram_visual_type(self.visual_type) and bool(self.resolved_diagram_labels())


def is_diagram_beat(beat: VisualBeat) -> bool:
    from agent.skills.media_sources.ai.prompt_builder import is_diagram_visual_type

    return is_diagram_visual_type(beat.visual_type)


def effective_min_duration(
    beat: VisualBeat,
    *,
    is_short: bool,
    config: ChannelRuntimeConfig | VisualBeatsConfig,
) -> float:
    if is_short:
        base = float(getattr(config, "min_image_duration_short_s", 2))
        diagram_min = float(getattr(config, "min_diagram_duration_short_s", 4.0))
    else:
        base = float(getattr(config, "min_image_duration_s", 4))
        diagram_min = float(getattr(config, "min_diagram_duration_s", 6.0))

    hint = float(beat.duration_hint_s or 0)
    if is_diagram_beat(beat):
        return max(base, diagram_min, hint)
    return max(base, hint) if hint > 0 else base


def parse_visual_beats(segment: dict[str, Any]) -> list[VisualBeat]:
    raw = segment.get("visual_beats") or []
    if not isinstance(raw, list):
        return []
    beats: list[VisualBeat] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            beats.append(VisualBeat.model_validate(item))
        except Exception as exc:
            logger.warning("Beat invalide ignoré segment %s : %s", segment.get("order"), exc)
    beats.sort(key=lambda b: b.order)
    return beats


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def validate_beats_against_narration(
    segment: dict[str, Any],
    *,
    vb_config: VisualBeatsConfig | None = None,
    is_short: bool = False,
) -> list[str]:
    """Retourne la liste des erreurs de validation (vide = OK)."""
    narration = (segment.get("narration_text") or "").strip()
    if not narration:
        return ["narration_text vide"]
    norm_narration = _normalize_text(narration)
    errors: list[str] = []
    beats = parse_visual_beats(segment)
    if not beats:
        return ["visual_beats absent ou vide"]

    min_diagram = 4.0 if is_short else 6.0
    if vb_config is not None:
        min_diagram = (
            float(vb_config.min_diagram_duration_short_s)
            if is_short
            else float(vb_config.min_diagram_duration_s)
        )

    for beat in beats:
        anchor = _normalize_text(beat.phrase_anchor)
        if len(anchor) < 4:
            errors.append(f"beat {beat.order}: phrase_anchor trop courte")
            continue
        if anchor not in norm_narration and not _fuzzy_anchor_in_text(anchor, norm_narration):
            errors.append(f"beat {beat.order}: phrase_anchor introuvable dans narration")

        if is_diagram_beat(beat):
            if not beat.resolved_diagram_labels():
                errors.append(f"beat {beat.order}: diagram_labels ou on_screen_text requis")
            hint = beat.duration_hint_s
            if hint is None or float(hint) < min_diagram:
                errors.append(
                    f"beat {beat.order}: duration_hint_s requis (>= {min_diagram}s) pour diagramme"
                )
    return errors


def _fuzzy_anchor_in_text(anchor: str, narration: str) -> bool:
    words = anchor.split()
    if len(words) < 2:
        return False
    window = len(words)
    narr_words = narration.split()
    for i in range(len(narr_words) - window + 1):
        chunk = " ".join(narr_words[i : i + window])
        if chunk == anchor:
            return True
    return False


def segment_has_visual_beats(segment: dict[str, Any]) -> bool:
    return bool(parse_visual_beats(segment))


def beats_to_dicts(beats: list[VisualBeat]) -> list[dict[str, Any]]:
    return [b.model_dump() for b in beats]


def suggest_types_for_tone(editorial_tone: str, theme_category: str) -> list[str]:
    from agent.skills.media_sources.ai.prompt_builder import (
        editorial_tags_for_type,
        list_visual_types,
    )

    tone = (editorial_tone or "").lower()
    category = (theme_category or "").lower()
    scored: list[tuple[int, str]] = []
    for vtype in list_visual_types():
        tags = editorial_tags_for_type(vtype)
        score = 0
        for tag in tags:
            if tag in tone or tag in category:
                score += 2
        if category and category in tags:
            score += 3
        scored.append((score, vtype))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t for s, t in scored if s > 0][:12] or list_visual_types()[:10]


def format_visual_type_catalog(
    editorial_tone: str = "",
    theme_category: str = "",
) -> str:
    from agent.skills.media_sources.ai.prompt_builder import build_visual_type_catalog

    return build_visual_type_catalog(editorial_tone, theme_category)
