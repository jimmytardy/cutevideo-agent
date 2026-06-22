from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.core.json_parse import parse_gemini_response
from agent.core.llm_retry import retry_transient_sync

logger = logging.getLogger(__name__)

SYNTHESIS_MODEL = "gemini-2.5-flash"
SYNTHESIS_FALLBACK = "gemini-2.5-flash-lite"
SYNTHESIS_MODELS = (SYNTHESIS_MODEL, SYNTHESIS_FALLBACK)

# FLUX rewards long descriptive prompts — keep room for a layered scene description.
MAX_SUBJECT_CHARS = 480

SYNTHESIS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject_en": {"type": "string"},
    },
    "required": ["subject_en"],
}

SYNTHESIS_PROMPT = """You convert French visual briefs into rich, descriptive English image-generation subjects for FLUX.

Visual type: {visual_type}
Style hint: {style_hint}
Narration anchor: {phrase_anchor}

French brief (DO NOT copy text/label instructions into output):
{prompt_fr}

Return ONLY this JSON:
{{"subject_en": "..."}}

Rules:
- English only, 200 to 480 characters — FLUX rewards detailed, descriptive prompts.
- Describe the scene in LAYERS: main subject and its action FIRST, then the immediate
  surroundings, then the background. This depth helps FLUX compose the image.
- Be concrete and visual: objects, materials, textures, colors, and the mood/atmosphere.
- Describe ONLY what to DRAW. REMOVE all mentions of labels, captions, titles, legends,
  on-screen text, or numbers to display.
- Do NOT add camera/lighting tags (lens, aperture, "shot on…") — those are appended later.
- No complete sentences suitable as a title banner.
- Keep proper nouns when visually relevant (e.g. Leaning Tower of Pisa).
- For diagrams/infographics: icons, arrows and shapes only — no readable text in the image."""

_TEXT_NOISE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:labels?|légendes?|texte|titres?|légende)\b[^.]*\.?", re.IGNORECASE),
    re.compile(r"\b(?:indiquent?|affichent?|précisent?|montrent?)\s+(?:clairement\s+)?(?:le|la|les|l')", re.IGNORECASE),
    re.compile(r"\b(?:à l'écran|on-?screen|caption)\b[^.]*\.?", re.IGNORECASE),
)


def _cache_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / f"flux_subject_{cache_key}.json"


def _cache_key(visual_type: str, prompt_fr: str, style_hint: str) -> str:
    payload = f"{visual_type}|{prompt_fr}|{style_hint}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _load_cached_subject(cache_dir: Path, cache_key: str) -> str | None:
    path = _cache_path(cache_dir, cache_key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        subject = data.get("subject_en") if isinstance(data, dict) else None
        if isinstance(subject, str) and subject.strip():
            return subject.strip()[:MAX_SUBJECT_CHARS]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Cache subject illisible %s : %s", path, exc)
    return None


def _save_cached_subject(cache_dir: Path, cache_key: str, subject_en: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, cache_key)
    path.write_text(
        json.dumps({"subject_en": subject_en[:MAX_SUBJECT_CHARS]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fallback_sanitize_subject(prompt_fr: str, *, style_hint: str = "") -> str:
    """Heuristique FR→EN minimal quand Gemini est indisponible."""
    text = (prompt_fr or "").strip()
    for pattern in _TEXT_NOISE_PATTERNS:
        text = pattern.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" .,-")
    if style_hint.strip():
        text = f"{text}. {style_hint.strip()}" if text else style_hint.strip()
    if not text:
        return "Educational illustration, icons and arrows only, no text"
    return text[:MAX_SUBJECT_CHARS]


def _synthesize_sync(
    *,
    visual_type: str,
    prompt_fr: str,
    style_hint: str,
    phrase_anchor: str,
    api_key: str,
) -> str:
    from google import genai
    from google.genai import types

    prompt = SYNTHESIS_PROMPT.format(
        visual_type=visual_type or "custom",
        style_hint=style_hint or "(none)",
        phrase_anchor=(phrase_anchor or "")[:120],
        prompt_fr=(prompt_fr or "")[:800],
    )
    client = genai.Client(api_key=api_key)
    errors: list[str] = []

    for model_name in SYNTHESIS_MODELS:
        try:
            response = retry_transient_sync(
                lambda model_name=model_name: client.models.generate_content(
                    model=model_name,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=512,
                        response_mime_type="application/json",
                        response_json_schema=SYNTHESIS_RESPONSE_SCHEMA,
                    ),
                ),
                label=f"prompt_synth/{model_name}",
            )
            data = parse_gemini_response(response, model_name, required_field="subject_en")
            subject = str(data.get("subject_en", "")).strip()
            if not subject:
                raise ValueError("subject_en vide")
            return subject[:MAX_SUBJECT_CHARS]
        except Exception as exc:
            errors.append(f"{model_name}: {exc}")
            logger.warning("Synthèse prompt FLUX %s échouée : %s", model_name, exc)

    raise RuntimeError("; ".join(errors) if errors else "synthèse Gemini échouée")


async def synthesize_flux_subject(
    *,
    visual_type: str,
    prompt_fr: str,
    style_hint: str = "",
    phrase_anchor: str = "",
    api_key: str | None = None,
    cache_dir: Path | None = None,
) -> str:
    """Traduit et sanitise un brief FR en subject EN pour FLUX/Imagen."""
    key = _cache_key(visual_type, prompt_fr, style_hint)
    if cache_dir is not None:
        cached = _load_cached_subject(cache_dir, key)
        if cached:
            return cached

    subject_en: str | None = None
    if api_key:
        try:
            subject_en = await asyncio.to_thread(
                _synthesize_sync,
                visual_type=visual_type,
                prompt_fr=prompt_fr,
                style_hint=style_hint,
                phrase_anchor=phrase_anchor,
                api_key=api_key,
            )
        except Exception as exc:
            logger.warning("Synthèse Gemini indisponible — fallback heuristique : %s", exc)

    if not subject_en:
        subject_en = fallback_sanitize_subject(prompt_fr, style_hint=style_hint)

    if cache_dir is not None:
        _save_cached_subject(cache_dir, key, subject_en)

    return subject_en


# --------------------------------------------------------------------------- #
# Search anchor — traduit l'entité du sujet en termes de recherche stock EN.   #
# Les banques (Unsplash, Pexels, Wikimedia) sont indexées en anglais : ancrer  #
# la recherche sur l'entité concrète traduite améliore radicalement la         #
# pertinence (cf. « moai easter island » vs « statues île de Pâques »).        #
# --------------------------------------------------------------------------- #

ANCHOR_MAX_TERMS = 5
ANCHOR_MAX_CHARS = 80

ANCHOR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "anchor_en": {"type": "string"},
        "terms_en": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["anchor_en"],
}

ANCHOR_PROMPT = """You convert a French video subject into English stock-image search terms.
Stock libraries (Unsplash, Pexels, Wikimedia Commons) are indexed in English.

French subject entity: {subject_entity}
Must visually include (FR, optional): {must_include}

Return ONLY this JSON:
{{"anchor_en": "...", "terms_en": ["...", "..."]}}

Rules:
- English only.
- "anchor_en": the SINGLE most recognizable proper noun / place / monument / species /
  object for this subject — 1 to 4 words, no sentence, no punctuation.
  Example: "statues de l'île de Pâques" -> "moai easter island".
  Example: "le manchot empereur" -> "emperor penguin".
- "terms_en": 2 to 5 additional CONCRETE English search terms (specific places, landmarks,
  objects, named features) tied to the subject.
- Forbidden in terms_en: generic category words alone (history, nature, culture, science,
  ancient, mystery), adjectives without a noun, full phrases.
- Keep proper nouns. Lowercase, words separated by single spaces."""


@dataclass(frozen=True)
class SearchAnchor:
    """Ancre de recherche stock en anglais dérivée de l'entité du sujet."""

    anchor_en: str = ""
    terms_en: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return bool(self.anchor_en.strip())


def _anchor_cache_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / f"search_anchor_{cache_key}.json"


def _anchor_cache_key(subject_entity: str, must_include: list[str]) -> str:
    payload = f"{subject_entity}|{'|'.join(must_include)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _clean_terms(terms: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(terms, list):
        for term in terms:
            cleaned = re.sub(r"\s+", " ", str(term)).strip().lower()[:ANCHOR_MAX_CHARS]
            key = cleaned
            if cleaned and key not in seen:
                seen.add(key)
                out.append(cleaned)
            if len(out) >= ANCHOR_MAX_TERMS:
                break
    return out


def _load_cached_anchor(cache_dir: Path, cache_key: str) -> SearchAnchor | None:
    path = _anchor_cache_path(cache_dir, cache_key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and str(data.get("anchor_en", "")).strip():
            return SearchAnchor(
                anchor_en=str(data["anchor_en"]).strip()[:ANCHOR_MAX_CHARS],
                terms_en=_clean_terms(data.get("terms_en")),
            )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Cache search anchor illisible %s : %s", path, exc)
    return None


def _save_cached_anchor(cache_dir: Path, cache_key: str, anchor: SearchAnchor) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _anchor_cache_path(cache_dir, cache_key)
    path.write_text(
        json.dumps(
            {"anchor_en": anchor.anchor_en, "terms_en": anchor.terms_en},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _translate_anchor_sync(
    *, subject_entity: str, must_include: list[str], api_key: str
) -> SearchAnchor:
    from google import genai
    from google.genai import types

    prompt = ANCHOR_PROMPT.format(
        subject_entity=(subject_entity or "")[:200],
        must_include=", ".join(must_include[:6]) or "(none)",
    )
    client = genai.Client(api_key=api_key)
    errors: list[str] = []

    for model_name in SYNTHESIS_MODELS:
        try:
            response = retry_transient_sync(
                lambda model_name=model_name: client.models.generate_content(
                    model=model_name,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        max_output_tokens=256,
                        response_mime_type="application/json",
                        response_json_schema=ANCHOR_RESPONSE_SCHEMA,
                    ),
                ),
                label=f"search_anchor/{model_name}",
            )
            data = parse_gemini_response(response, model_name, required_field="anchor_en")
            anchor = str(data.get("anchor_en", "")).strip().lower()[:ANCHOR_MAX_CHARS]
            if not anchor:
                raise ValueError("anchor_en vide")
            return SearchAnchor(anchor_en=anchor, terms_en=_clean_terms(data.get("terms_en")))
        except Exception as exc:
            errors.append(f"{model_name}: {exc}")
            logger.warning("Traduction search anchor %s échouée : %s", model_name, exc)

    raise RuntimeError("; ".join(errors) if errors else "traduction Gemini échouée")


async def translate_search_anchor(
    *,
    subject_entity: str,
    must_include: list[str] | None = None,
    api_key: str | None = None,
    cache_dir: Path | None = None,
) -> SearchAnchor:
    """Traduit l'entité du sujet (FR) en ancre + termes de recherche stock (EN).

    Retombe sur l'entité brute si Gemini est indisponible (jamais de régression).
    """
    subject_entity = (subject_entity or "").strip()
    must_include = [m for m in (must_include or []) if m]
    if not subject_entity:
        return SearchAnchor()

    key = _anchor_cache_key(subject_entity, must_include)
    if cache_dir is not None:
        cached = _load_cached_anchor(cache_dir, key)
        if cached:
            return cached

    anchor: SearchAnchor | None = None
    if api_key:
        try:
            anchor = await asyncio.to_thread(
                _translate_anchor_sync,
                subject_entity=subject_entity,
                must_include=must_include,
                api_key=api_key,
            )
        except Exception as exc:
            logger.warning("Traduction anchor indisponible — fallback entité brute : %s", exc)

    if anchor is None or not anchor.is_usable:
        # Fallback : on garde l'entité telle quelle (mieux que le titre verbeux).
        anchor = SearchAnchor(anchor_en=subject_entity.lower()[:ANCHOR_MAX_CHARS], terms_en=[])

    if cache_dir is not None:
        _save_cached_anchor(cache_dir, key, anchor)

    return anchor
