from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent.core.config import load_agent_config
from agent.core.json_parse import is_json_parse_failure, parse_gemini_response
from agent.core.research_models import ResearchBrief

logger = logging.getLogger(__name__)

RESEARCH_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "required": [
        "subject_entity",
        "key_facts",
        "timeline",
        "sources",
        "visual_anchors",
        "common_misconceptions",
        "narrative_angles",
        "confidence",
        "niche_risk",
    ],
    "properties": {
        "subject_entity": {"type": "STRING"},
        "key_facts": {"type": "ARRAY", "items": {"type": "STRING"}},
        "timeline": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "year": {"type": "STRING"},
                    "event": {"type": "STRING"},
                },
            },
        },
        "sources": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "url": {"type": "STRING"},
                    "snippet": {"type": "STRING"},
                },
            },
        },
        "visual_anchors": {"type": "ARRAY", "items": {"type": "STRING"}},
        "common_misconceptions": {"type": "ARRAY", "items": {"type": "STRING"}},
        "narrative_angles": {"type": "ARRAY", "items": {"type": "STRING"}},
        "confidence": {"type": "NUMBER"},
        "niche_risk": {"type": "STRING"},
    },
}

RESEARCH_PROMPT = """Tu es un chercheur documentaire pour vidéos éducatives YouTube en français.
Utilise la recherche Google pour collecter des faits vérifiables sur le sujet ci-dessous.

SUJET VIDÉO : {theme}
CATÉGORIE CHAÎNE : {theme_category}
NICHE : {niche_prompt}
{content_plan_context}

Consignes :
1. Identifie l'entité précise du sujet (personne, espèce, événement, lieu, concept)
2. Collecte 8-15 faits vérifiables avec dates, chiffres, noms propres
3. Construis une chronologie si pertinent
4. Liste les idées reçues / confusions fréquentes à déconstruire
5. Propose 2-4 angles narratifs pour une vidéo éducative
6. Liste des ancres visuelles (éléments à illustrer précisément)
7. Cite jusqu'à {max_sources} sources web fiables (Wikipedia, institutions, presse reconnue)
8. Évalue niche_risk : low | medium | high (sujet rare ou peu documenté = high)
9. confidence entre 0 et 1 selon la qualité des sources trouvées

Retourne UNIQUEMENT le JSON demandé, sans markdown ni texte autour, en français.

Schéma JSON attendu :
{{
  "subject_entity": "string",
  "key_facts": ["string"],
  "timeline": [{{"year": "string", "event": "string"}}],
  "sources": [{{"title": "string", "url": "string", "snippet": "string"}}],
  "visual_anchors": ["string"],
  "common_misconceptions": ["string"],
  "narrative_angles": ["string"],
  "confidence": 0.0,
  "niche_risk": "low|medium|high"
}}"""

JSON_REFORMAT_PROMPT = """Ce texte est une réponse JSON mal formée.
Corrige UNIQUEMENT la syntaxe JSON. Ne modifie pas les faits, chiffres, URLs ni le sens.
Conserve tous les champs et valeurs présents.

TEXTE À CORRIGER :
{raw}"""


def _supports_structured_output_with_tools(model_name: str) -> bool:
    """Gemini 3+ autorise grounding et JSON schema dans le même appel."""
    return model_name.startswith("gemini-3")


def load_research_config() -> dict[str, Any]:
    cfg = load_agent_config().get("research", {})
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "model": str(cfg.get("model", "gemini-3.5-flash")),
        "fallback_model": str(cfg.get("fallback_model", "gemini-3.1-pro-preview")),
        "json_reformat_model": str(cfg.get("json_reformat_model", "gemini-2.5-flash-lite")),
        "max_sources": int(cfg.get("max_sources", 8)),
    }


def _reformat_research_json(
    client: Any,
    types: Any,
    broken_raw: str,
    reformat_model: str,
) -> dict[str, Any]:
    """Dernier recours : modèle léger sans grounding pour corriger la syntaxe JSON."""
    prompt = JSON_REFORMAT_PROMPT.format(raw=broken_raw[:12000])
    response = client.models.generate_content(
        model=reformat_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=8192,
            response_mime_type="application/json",
            response_json_schema=RESEARCH_RESPONSE_SCHEMA,
        ),
    )
    return parse_gemini_response(response, reformat_model)


def _call_research_model(
    client: Any,
    types: Any,
    model_name: str,
    prompt: str,
    *,
    reformat_model: str,
) -> dict[str, Any]:
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config_kwargs: dict[str, Any] = {
        "temperature": 0.2,
        "max_output_tokens": 8192,
        "tools": [grounding_tool],
    }
    if _supports_structured_output_with_tools(model_name):
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_json_schema"] = RESEARCH_RESPONSE_SCHEMA

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    try:
        return parse_gemini_response(response, model_name)
    except ValueError as exc:
        if not is_json_parse_failure(exc):
            raise
        raw = (getattr(response, "text", None) or "").strip()
        if not raw:
            raise
        logger.warning(
            "JSON recherche invalide (%s) — reformatage via %s",
            model_name,
            reformat_model,
        )
        return _reformat_research_json(client, types, raw, reformat_model)


async def run_gemini_research(
    *,
    theme: str,
    theme_category: str,
    niche_prompt: str,
    content_plan: dict[str, Any] | None,
    api_key: str,
    use_pro: bool = False,
) -> ResearchBrief:
    """Recherche factuelle via Gemini + Google Search grounding."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai non installé") from exc

    cfg = load_research_config()
    model = cfg["fallback_model"] if use_pro else cfg["model"]
    fallback = cfg["fallback_model"]

    plan_lines: list[str] = []
    if content_plan:
        if content_plan.get("subject"):
            plan_lines.append(f"Sujet mandaté : {content_plan['subject']}")
        entities = ", ".join(content_plan.get("main_entities") or [])
        if entities:
            plan_lines.append(f"Entités : {entities}")
    content_plan_context = "\n".join(plan_lines) if plan_lines else "(aucun mandat planner)"

    prompt = RESEARCH_PROMPT.format(
        theme=theme,
        theme_category=theme_category,
        niche_prompt=niche_prompt or "(général)",
        content_plan_context=content_plan_context,
        max_sources=cfg["max_sources"],
    )

    def _run() -> dict[str, Any]:
        client = genai.Client(api_key=api_key)
        reformat_model = cfg["json_reformat_model"]
        try:
            return _call_research_model(
                client,
                types,
                model,
                prompt,
                reformat_model=reformat_model,
            )
        except Exception as primary_exc:
            if fallback and fallback != model and not is_json_parse_failure(primary_exc):
                logger.warning(
                    "Recherche Gemini %s échouée (%s) — fallback %s",
                    model,
                    primary_exc,
                    fallback,
                )
                return _call_research_model(
                    client,
                    types,
                    fallback,
                    prompt,
                    reformat_model=reformat_model,
                )
            raise

    data = await asyncio.to_thread(_run)
    brief = ResearchBrief.from_dict(data)
    if brief is None:
        raise RuntimeError("Parsing ResearchBrief échoué")
    logger.info(
        "Recherche terminée : %s (%d faits, confiance %.2f, niche=%s)",
        brief.subject_entity,
        len(brief.key_facts),
        brief.confidence,
        brief.niche_risk,
    )
    return brief
