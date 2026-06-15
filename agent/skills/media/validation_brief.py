from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from agent.core.config import settings
from agent.core.llm_config import resolve_max_tokens, resolve_model
from agent.core.media_validation import (
    MediaValidationBrief,
    SegmentValidationBrief,
    attach_brief_to_segments,
    load_media_validation_defaults,
)

logger = logging.getLogger(__name__)

BRIEF_SYSTEM = """Tu es un expert en curation de médias visuels pour vidéos éducatives.
Tu produis des critères de validation précis pour filtrer images et vidéos stock.
Tu retournes UNIQUEMENT du JSON valide."""

BRIEF_PROMPT = """Analyse ce sujet vidéo et génère un brief de validation média strict.

SUJET VIDÉO : {theme}
CATÉGORIE : {theme_category}
BRIEF CRÉATIF CHAÎNE : {creative_brief}

SEGMENTS :
{segments_summary}

Détecte le type de sujet (subject_type) :
- species : espèce animale/végétale précise
- person : personnage historique ou contemporain identifié
- event : événement daté
- concept : concept scientifique ou abstrait
- place : lieu géographique précis
- artwork : œuvre d'art, style, artiste
- general : autre

Règles par type :
- species : exiger l'espèce exacte, lister les confusions visuelles fréquentes (ex. paon vs paradisier)
- person : exiger la bonne personne, période, contexte ; rejeter sosies/anachronismes
- event : exiger époque, lieu, éléments factuels ; rejeter reconstitutions fantaisistes
- concept : exiger illustration littérale du phénomène ; rejeter métaphores visuelles trompeuses
- place : exiger le bon lieu ; rejeter paysages génériques
- artwork : exiger la bonne œuvre/style ; rejeter œuvres d'autres mouvements

Évalue niche_risk :
- high : sujet très spécifique, peu de stock photo probable (espèce rare, événement obscur)
- medium : sujet identifiable mais stock limité
- low : sujet bien couvert par les banques d'images

min_relevance_score : {high_precision} si species/person/event précis, sinon {default_score}

Retourne UNIQUEMENT ce JSON :
{{
  "subject_entity": "entité précise du sujet",
  "subject_type": "species",
  "must_include": ["élément visuel obligatoire 1", "élément 2"],
  "must_exclude": ["confusion fréquente 1", "générique à éviter"],
  "ambiguity_warnings": ["piège de confusion 1"],
  "validation_prompt": "Paragraphe de 2-4 phrases pour guider l'évaluation visuelle Gemini",
  "min_relevance_score": 75,
  "niche_risk": "medium",
  "segments": {{
    "1": {{
      "must_include": ["spécifique segment 1"],
      "must_exclude": ["à éviter segment 1"],
      "validation_prompt": "critères segment 1",
      "min_relevance_score": null
    }}
  }}
}}

segments : une entrée par numéro d'order de segment (clés string)."""


async def build_validation_brief(
    *,
    theme: str,
    theme_category: str,
    segments: list[dict[str, Any]],
    creative_brief: str = "",
) -> MediaValidationBrief:
    """Génère un brief de validation média via Claude."""
    defaults = load_media_validation_defaults()
    segments_summary = _format_segments_summary(segments)
    prompt = BRIEF_PROMPT.format(
        theme=theme,
        theme_category=theme_category,
        creative_brief=creative_brief or "(aucun)",
        segments_summary=segments_summary,
        high_precision=defaults["relevance_min_score_high_precision"],
        default_score=defaults["relevance_min_score_default"],
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    model = resolve_model("scenario_agent")
    max_tokens = resolve_max_tokens("scenario_agent")

    msg = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=BRIEF_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    data = _parse_json(raw)
    brief = _parse_brief_payload(data, defaults)
    logger.info(
        "Brief validation média : %s (%s, niche=%s, seuil=%d)",
        brief.subject_entity,
        brief.subject_type,
        brief.niche_risk,
        brief.min_relevance_score,
    )
    return brief


def apply_brief_to_scenario_data(
    data: dict[str, Any],
    brief: MediaValidationBrief,
) -> dict[str, Any]:
    """Enrichit le JSON scénario avec media_validation par segment."""
    segments = data.get("segments", [])
    if not isinstance(segments, list):
        return data
    data = dict(data)
    data["segments"] = attach_brief_to_segments(segments, brief)
    data["media_validation_brief"] = brief.to_dict()
    return data


def _format_segments_summary(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for seg in segments[:12]:
        if not isinstance(seg, dict):
            continue
        order = seg.get("order", "?")
        title = seg.get("title", "")
        kws = ", ".join(seg.get("search_keywords", [])[:6])
        narration = (seg.get("narration_text") or "")[:200]
        lines.append(f"- Segment {order} « {title} » | mots-clés: {kws} | narration: {narration}")
    return "\n".join(lines) or "(aucun segment)"


def _parse_brief_payload(
    data: dict[str, Any],
    defaults: dict[str, Any],
) -> MediaValidationBrief:
    segments_raw = data.get("segments", {})
    segment_briefs: dict[int, SegmentValidationBrief] = {}
    if isinstance(segments_raw, dict):
        for key, val in segments_raw.items():
            if isinstance(val, dict):
                segment_briefs[int(key)] = SegmentValidationBrief.model_validate(val)

    subject_type = str(data.get("subject_type", "general"))
    if subject_type not in (
        "species", "person", "event", "concept", "place", "artwork", "general"
    ):
        subject_type = "general"

    niche_risk = str(data.get("niche_risk", "low"))
    if niche_risk not in ("low", "medium", "high"):
        niche_risk = "low"

    default_score = int(defaults["relevance_min_score_default"])
    high_precision = int(defaults["relevance_min_score_high_precision"])
    min_score = int(data.get("min_relevance_score", default_score))
    if subject_type == "species" and min_score == default_score:
        min_score = high_precision

    return MediaValidationBrief(
        subject_entity=str(data.get("subject_entity", "")),
        subject_type=subject_type,  # type: ignore[arg-type]
        must_include=[str(x) for x in data.get("must_include", []) if x],
        must_exclude=[str(x) for x in data.get("must_exclude", []) if x],
        ambiguity_warnings=[str(x) for x in data.get("ambiguity_warnings", []) if x],
        validation_prompt=str(data.get("validation_prompt", "")),
        min_relevance_score=min_score,
        niche_risk=niche_risk,  # type: ignore[arg-type]
        segments=segment_briefs,
    )


def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(raw)
