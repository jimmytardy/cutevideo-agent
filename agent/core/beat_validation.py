from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agent.core.media_validation import MediaValidationBrief, _merge_unique_lists
from agent.core.visual_beats import VisualBeat, beat_narration_excerpt, parse_visual_beats
from agent.skills.media.beat_source_routing import DEFAULT_AI_ONLY_VISUAL_TYPES
from agent.skills.media_sources.ai.prompt_builder import DIAGRAM_VISUAL_TYPES

if TYPE_CHECKING:
    pass

WILDLIFE_VISUAL_TYPES: frozenset[str] = frozenset({
    "wildlife_action",
    "macro_detail",
    "underwater",
    "weather_phenomenon",
    "habitat_wide",
    "aerial",
    "establishing_shot",
})

ARCHIVAL_VISUAL_TYPES: frozenset[str] = frozenset({
    "archival_footage",
    "portrait_historical",
    "historical_artifact",
    "period_reenactment",
    "document_closeup",
    "press_photo",
    "crime_documentary",
    "courtroom",
    "evidence_detail",
    "political_figure",
    "protest_scene",
    "news_broll",
})

ARTWORK_VISUAL_TYPES: frozenset[str] = frozenset({
    "artwork",
    "museum_interior",
    "institution_building",
})

SPORTS_VISUAL_TYPES: frozenset[str] = frozenset({
    "sports_action",
    "stadium_establishing",
    "sports_celebration",
    "athlete_portrait",
})

DIAGRAM_SCORE_ADJUSTMENT = -5


class BeatValidationContext(BaseModel):
    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    validation_prompt: str = ""
    min_relevance_score: int = 60
    layers: list[str] = Field(default_factory=list)
    visual_type: str = ""
    phrase_anchor: str = ""
    prompt: str = ""
    spoken_text: str = ""


class VisualTypeTemplate(BaseModel):
    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    validation_prompt: str = ""
    score_adjustment: int = 0


def _visual_type_template(visual_type: str) -> VisualTypeTemplate:
    if visual_type in DIAGRAM_VISUAL_TYPES or visual_type in DEFAULT_AI_ONLY_VISUAL_TYPES:
        return VisualTypeTemplate(
            must_include=["clarté visuelle", "éléments illustratifs lisibles"],
            must_exclude=[
                "métaphore visuelle trompeuse",
                "carte ou schéma générique",
                "texte lisible ou pseudo-texte dans l'image",
                "cadres vides ou bandeau titre",
                "titres illisibles générés par IA",
            ],
            validation_prompt=(
                "Valider la lisibilité et la pertinence pédagogique du visuel explicatif. "
                "Le média doit correspondre au type diagramme/schéma attendu. "
                "Rejeter si texte, pseudo-texte, cadres vides ou bandeau titre visible dans l'image."
            ),
            score_adjustment=DIAGRAM_SCORE_ADJUSTMENT,
        )
    if visual_type in WILDLIFE_VISUAL_TYPES:
        return VisualTypeTemplate(
            must_include=["sujet naturel identifiable"],
            must_exclude=["stock générique sans lien", "mauvaise espèce ou mauvais habitat"],
            validation_prompt=(
                "Valider l'exactitude de l'espèce, du comportement ou du paysage naturel."
            ),
        )
    if visual_type in ARCHIVAL_VISUAL_TYPES:
        return VisualTypeTemplate(
            must_include=["contexte historique ou documentaire crédible"],
            must_exclude=["anachronisme", "reconstitution fantaisiste", "sosie"],
            validation_prompt=(
                "Valider la cohérence d'époque, de lieu et du contexte documentaire."
            ),
        )
    if visual_type in ARTWORK_VISUAL_TYPES:
        return VisualTypeTemplate(
            must_include=["œuvre ou style attendu"],
            must_exclude=["œuvre d'un autre mouvement", "reproduction incorrecte"],
            validation_prompt="Valider l'exactitude de l'œuvre, du style ou du lieu culturel.",
        )
    if visual_type in SPORTS_VISUAL_TYPES:
        return VisualTypeTemplate(
            must_include=["action ou contexte sportif identifiable"],
            must_exclude=["sport ou discipline incorrecte", "stock générique"],
            validation_prompt="Valider le sport, l'athlète ou le lieu de compétition.",
        )
    if visual_type == "custom":
        return VisualTypeTemplate(
            must_exclude=["visuel trop générique", "hors-sujet"],
            validation_prompt="Valider la correspondance littérale avec l'intention visuelle décrite.",
        )
    return VisualTypeTemplate(
        must_exclude=["visuel trop générique", "hors-sujet"],
        validation_prompt="Valider la correspondance avec l'intention visuelle du beat.",
    )


def _prompt_keywords(beat: VisualBeat) -> list[str]:
    words = [w.strip() for w in beat.prompt.split() if len(w.strip()) > 3]
    return words[:4]


def resolve_beat_validation(
    beat: VisualBeat,
    *,
    brief: MediaValidationBrief,
    segment_order: int,
) -> BeatValidationContext:
    """Fusionne brief global, segment et template visual_type pour un beat."""
    seg = brief.segment_brief(segment_order)
    template = _visual_type_template(beat.visual_type)
    layers: list[str] = ["global"]

    must_include = list(brief.must_include)
    must_exclude = list(brief.must_exclude)
    validation_parts: list[str] = []
    if brief.validation_prompt.strip():
        validation_parts.append(brief.validation_prompt.strip())

    if segment_order in brief.segments:
        layers.append("segment")
        must_include = _merge_unique_lists(must_include, seg.must_include)
        must_exclude = _merge_unique_lists(must_exclude, seg.must_exclude)
        if seg.validation_prompt.strip():
            validation_parts.append(seg.validation_prompt.strip())

    layers.append(f"visual_type:{beat.visual_type}")
    must_include = _merge_unique_lists(
        must_include,
        template.must_include,
        _prompt_keywords(beat),
    )
    must_exclude = _merge_unique_lists(must_exclude, template.must_exclude)
    if template.validation_prompt.strip():
        validation_parts.append(template.validation_prompt.strip())

    if beat.prompt.strip():
        must_include = _merge_unique_lists(must_include, [beat.prompt.strip()])

    base_score = brief.min_score_for_segment(segment_order)
    min_score = max(40, base_score + template.score_adjustment)

    return BeatValidationContext(
        must_include=must_include,
        must_exclude=must_exclude,
        validation_prompt="\n".join(validation_parts),
        min_relevance_score=min_score,
        layers=layers,
        visual_type=beat.visual_type,
        phrase_anchor=beat.phrase_anchor,
        prompt=beat.prompt,
        spoken_text=beat_narration_excerpt(beat),
    )


def resolve_segment_classic_validation(
    *,
    brief: MediaValidationBrief,
    segment_order: int,
) -> BeatValidationContext:
    """Critères pour un segment sans visual_beats (mode classique)."""
    seg = brief.segment_brief(segment_order)
    layers = ["global"]
    if segment_order in brief.segments:
        layers.append("segment")

    return BeatValidationContext(
        must_include=list(seg.must_include) or list(brief.must_include),
        must_exclude=list(seg.must_exclude) or list(brief.must_exclude),
        validation_prompt=seg.validation_prompt or brief.validation_prompt,
        min_relevance_score=brief.min_score_for_segment(segment_order),
        layers=layers + ["segment_classic"],
    )


def resolve_beats_for_scenario(
    brief: MediaValidationBrief,
    segments: list[dict[str, Any]] | None,
) -> list[BeatValidationContext]:
    """Liste les contextes résolus pour chaque beat (ou segment classique)."""
    if not segments:
        return []

    results: list[tuple[int, int | None, str, BeatValidationContext]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        order = int(seg.get("order", 0))
        title = str(seg.get("title", "") or f"Segment {order}")
        beats = parse_visual_beats(seg)
        if beats:
            for beat in beats:
                ctx = resolve_beat_validation(beat, brief=brief, segment_order=order)
                results.append((order, beat.order, title, ctx))
        else:
            ctx = resolve_segment_classic_validation(brief=brief, segment_order=order)
            results.append((order, None, title, ctx))

    results.sort(key=lambda item: (item[0], item[1] if item[1] is not None else 0))
    return [item[3] for item in results]


def resolve_beats_for_response(
    brief: MediaValidationBrief,
    segments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Payload sérialisable pour l'API dashboard."""
    if not segments:
        return []

    out: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        order = int(seg.get("order", 0))
        title = str(seg.get("title", "") or f"Segment {order}")
        beats = parse_visual_beats(seg)
        if beats:
            for beat in beats:
                ctx = resolve_beat_validation(beat, brief=brief, segment_order=order)
                out.append({
                    "segment_order": order,
                    "beat_order": beat.order,
                    "segment_title": title,
                    "visual_type": beat.visual_type,
                    "phrase_anchor": beat.phrase_anchor,
                    "prompt": beat.prompt,
                    "must_include": ctx.must_include,
                    "must_exclude": ctx.must_exclude,
                    "validation_prompt": ctx.validation_prompt,
                    "min_relevance_score": ctx.min_relevance_score,
                    "layers": ctx.layers,
                })
        else:
            ctx = resolve_segment_classic_validation(brief=brief, segment_order=order)
            out.append({
                "segment_order": order,
                "beat_order": None,
                "segment_title": title,
                "visual_type": None,
                "phrase_anchor": None,
                "prompt": None,
                "must_include": ctx.must_include,
                "must_exclude": ctx.must_exclude,
                "validation_prompt": ctx.validation_prompt,
                "min_relevance_score": ctx.min_relevance_score,
                "layers": ctx.layers,
            })

    out.sort(key=lambda item: (item["segment_order"], item["beat_order"] or 0))
    return out
