from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.json_parse import parse_gemini_response
from agent.core.media_validation import MediaValidationBrief, SegmentValidationBrief

logger = logging.getLogger(__name__)

RELEVANCE_MODEL = "gemini-2.5-flash"
RELEVANCE_FALLBACK_MODEL = "gemini-2.5-flash-lite"
RELEVANCE_MODELS = (RELEVANCE_MODEL, RELEVANCE_FALLBACK_MODEL, "gemini-2.5-pro")

SCORING_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                    "rejection_category": {"type": "string"},
                },
                "required": ["index", "score", "reason", "rejection_category"],
            },
        },
    },
    "required": ["scores"],
}

RELEVANCE_PROMPT_BASE = """Tu évalues la pertinence de médias (images ou vidéos) pour un segment de vidéo éducative.

Sujet de la vidéo : {video_subject}
Catégorie chaîne : {channel_category}
Titre du segment : {segment_title}
Extrait narration : {segment_narration}

{validation_criteria}

Pour chaque média numéroté, indique s'il illustre précisément le sujet ET le segment.
Score < 30 si confusion taxonomique, anachronisme ou hors-sujet flagrant.

Retourne UNIQUEMENT ce JSON (sans markdown) :
{{
  "scores": [
    {{"index": 0, "score": 85, "reason": "Courte explication", "rejection_category": "ok"}},
    {{"index": 1, "score": 25, "reason": "Paon au lieu de paradisier", "rejection_category": "wrong_species"}}
  ]
}}

Règles :
- score entre 0 et 100
- un score par média fourni (index 0 à N-1)
- reason : maximum 80 caractères
- rejection_category : ok | wrong_species | generic | anachronism | wrong_place | wrong_person | off_topic | low_quality"""

VALIDATION_CRITERIA_TEMPLATE = """CRITÈRES OBLIGATOIRES :
- Sujet précis : {subject_entity}
- Type de sujet : {subject_type}
- DOIT montrer : {must_include}
- NE DOIT PAS montrer : {must_exclude}
- Pièges connus : {ambiguity_warnings}
{validation_prompt}"""


@dataclass
class ScoredCandidate:
    candidate: dict[str, Any]
    score: int
    reason: str
    rejection_category: str = "ok"


class MediaRelevanceScoringError(RuntimeError):
    """Échec du scoring Gemini — le pipeline ne doit pas continuer sans validation."""


def build_relevance_prompt(
    *,
    video_subject: str,
    channel_category: str,
    segment_title: str,
    segment_narration: str,
    validation_brief: MediaValidationBrief | SegmentValidationBrief | None = None,
    segment_order: int | None = None,
) -> str:
    if validation_brief is None:
        validation_criteria = (
            "Pénalise les visuels trop génériques, hors-sujet ou anachroniques."
        )
    elif isinstance(validation_brief, MediaValidationBrief) and segment_order is not None:
        seg = validation_brief.segment_brief(segment_order)
        validation_criteria = VALIDATION_CRITERIA_TEMPLATE.format(
            subject_entity=validation_brief.subject_entity or video_subject,
            subject_type=validation_brief.subject_type,
            must_include=", ".join(seg.must_include or validation_brief.must_include) or "(non spécifié)",
            must_exclude=", ".join(seg.must_exclude or validation_brief.must_exclude) or "(non spécifié)",
            ambiguity_warnings=", ".join(validation_brief.ambiguity_warnings) or "(aucun)",
            validation_prompt=seg.validation_prompt or validation_brief.validation_prompt,
        )
    elif isinstance(validation_brief, SegmentValidationBrief):
        validation_criteria = VALIDATION_CRITERIA_TEMPLATE.format(
            subject_entity=video_subject,
            subject_type="general",
            must_include=", ".join(validation_brief.must_include) or "(non spécifié)",
            must_exclude=", ".join(validation_brief.must_exclude) or "(non spécifié)",
            ambiguity_warnings="(aucun)",
            validation_prompt=validation_brief.validation_prompt,
        )
    else:
        validation_criteria = VALIDATION_CRITERIA_TEMPLATE.format(
            subject_entity=validation_brief.subject_entity or video_subject,
            subject_type=validation_brief.subject_type,
            must_include=", ".join(validation_brief.must_include) or "(non spécifié)",
            must_exclude=", ".join(validation_brief.must_exclude) or "(non spécifié)",
            ambiguity_warnings=", ".join(validation_brief.ambiguity_warnings) or "(aucun)",
            validation_prompt=validation_brief.validation_prompt,
        )

    return RELEVANCE_PROMPT_BASE.format(
        video_subject=video_subject[:200],
        channel_category=channel_category,
        segment_title=segment_title[:120],
        segment_narration=(segment_narration or "")[:400],
        validation_criteria=validation_criteria,
    )


def _is_model_unavailable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "404" in msg
        or "no longer available" in msg
        or ("not found" in msg and "model" in msg)
    )


def _is_auth_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "401" in msg or "unauthenticated" in msg or "api key not valid" in msg


def _auth_error_message(model_name: str) -> str:
    return (
        "Scoring de pertinence média impossible : GOOGLE_GEMINI_API_KEY invalide, "
        f"expirée ou révoquée ({model_name}). "
        "Vérifiez la clé dans Google AI Studio (https://aistudio.google.com/apikey), "
        "mettez à jour .env puis redémarrez le conteneur."
    )


def _is_retriable_scoring_error(exc: Exception) -> bool:
    if _is_model_unavailable(exc):
        return True
    msg = str(exc).lower()
    if "500" in msg or "internal error" in msg or "internal_error" in msg:
        return True
    return any(
        token in msg
        for token in ("json invalide", "réponse vide", "jsondecodeerror", "non évalué")
    )


def _parse_scoring_payload(response: Any, model_name: str) -> dict[str, Any]:
    return parse_gemini_response(response, model_name, required_field="scores")


async def score_media_candidates(
    candidates: list[dict[str, Any]],
    *,
    video_subject: str,
    channel_category: str,
    segment_title: str,
    segment_narration: str,
    api_key: str,
    cache_dir: Path | None = None,
    validation_brief: MediaValidationBrief | SegmentValidationBrief | None = None,
    segment_order: int | None = None,
) -> list[ScoredCandidate]:
    """Score les candidats médias via Gemini Flash vision. Retourne liste triée par score décroissant."""
    if not candidates:
        return []

    if not api_key:
        raise MediaRelevanceScoringError(
            "Scoring de pertinence média impossible : GOOGLE_GEMINI_API_KEY non configurée."
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise MediaRelevanceScoringError(
            "Scoring de pertinence média impossible : package google-genai absent."
        ) from exc

    thumb_paths = await _download_thumbnails(candidates, cache_dir)
    if not any(thumb_paths):
        raise MediaRelevanceScoringError(
            "Scoring de pertinence média impossible : aucune miniature téléchargeable "
            "pour évaluer les candidats."
        )

    prompt = build_relevance_prompt(
        video_subject=video_subject,
        channel_category=channel_category,
        segment_title=segment_title,
        segment_narration=segment_narration,
        validation_brief=validation_brief,
        segment_order=segment_order,
    )
    contents = _build_contents(candidates, thumb_paths, prompt)

    def _score() -> list[ScoredCandidate]:
        errors: list[str] = []
        for auth_attempt in range(2):
            client = genai.Client(api_key=api_key)
            for model_name in RELEVANCE_MODELS:
                try:
                    return _score_with_model(
                        client,
                        types,
                        model_name,
                        contents,
                        candidates,
                    )
                except Exception as exc:
                    errors.append(f"{model_name}: {exc}")
                    if _is_auth_error(exc):
                        if auth_attempt == 0:
                            logger.warning(
                                "Scoring Gemini auth échoué (%s) — retry",
                                model_name,
                            )
                            break
                        raise MediaRelevanceScoringError(
                            _auth_error_message(model_name)
                        ) from exc
                    if _is_retriable_scoring_error(exc):
                        logger.warning("Scoring Gemini (%s) échoué : %s", model_name, exc)
                        continue
                    raise MediaRelevanceScoringError(
                        "Scoring de pertinence média impossible : "
                        f"{model_name} — {exc}"
                    ) from exc
            else:
                break
        raise MediaRelevanceScoringError(
            "Scoring de pertinence média impossible : tous les modèles Gemini ont échoué "
            f"({', '.join(RELEVANCE_MODELS)}) — {' ; '.join(errors)}"
        )

    return await asyncio.to_thread(_score)


def _build_contents(
    candidates: list[dict[str, Any]],
    thumb_paths: list[Path | None],
    prompt: str,
) -> list[Any]:
    from google.genai import types

    contents: list[Any] = [prompt]
    for i, path in enumerate(thumb_paths):
        if path and path.exists():
            contents.append(f"Média {i} — {candidates[i].get('title', '')}")
            contents.append(
                types.Part.from_bytes(data=path.read_bytes(), mime_type=_mime_for(path))
            )
        else:
            meta = candidates[i]
            contents.append(
                f"Média {i} (métadonnées seules) : source={meta.get('source')}, "
                f"type={meta.get('asset_type', 'image')}, "
                f"title={meta.get('title', '')}, url={meta.get('url', '')}"
            )
    return contents


def _score_with_model(
    client: Any,
    types: Any,
    model_name: str,
    contents: list[Any],
    candidates: list[dict[str, Any]],
) -> list[ScoredCandidate]:
    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=max(2048, len(candidates) * 256),
            response_mime_type="application/json",
            response_json_schema=SCORING_RESPONSE_SCHEMA,
        ),
    )
    data = _parse_scoring_payload(response, model_name)
    score_map: dict[int, tuple[int, str, str]] = {}
    for item in data.get("scores", []):
        if isinstance(item, dict) and "index" in item:
            score_map[int(item["index"])] = (
                int(item.get("score", 0)),
                str(item.get("reason", "")),
                str(item.get("rejection_category", "ok")),
            )
    scored: list[ScoredCandidate] = []
    for i, candidate in enumerate(candidates):
        if i not in score_map:
            raise ValueError(f"JSON invalide de {model_name} : score manquant pour l'index {i}")
        score, reason, category = score_map[i]
        scored.append(
            ScoredCandidate(
                candidate=candidate,
                score=score,
                reason=reason,
                rejection_category=category,
            )
        )
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


async def _download_thumbnails(
    candidates: list[dict[str, Any]],
    cache_dir: Path | None,
) -> list[Path | None]:
    import aiohttp

    out_dir = cache_dir or Path("./tmp/media_scoring")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path | None] = []

    async with aiohttp.ClientSession() as session:
        for i, item in enumerate(candidates):
            local = item.get("local_generated")
            if local and Path(local).exists():
                paths.append(Path(local))
                continue
            preview_url = item.get("thumbnail_url") or item.get("url")
            if not preview_url or preview_url.startswith("/"):
                paths.append(None)
                continue
            url_suffix = Path(preview_url.split("?")[0]).suffix.lower()
            suffix = url_suffix if url_suffix in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
            dest = out_dir / f"candidate_{i}{suffix}"
            if dest.exists():
                paths.append(dest)
                continue
            try:
                async with session.get(preview_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        dest.write_bytes(await resp.read())
                        paths.append(dest)
                    else:
                        paths.append(None)
            except Exception:
                paths.append(None)
    return paths


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".png",):
        return "image/png"
    if suffix in (".webp",):
        return "image/webp"
    if suffix in (".mp4", ".webm", ".mov"):
        return "video/mp4"
    return "image/jpeg"
