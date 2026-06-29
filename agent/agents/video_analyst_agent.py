from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.skills.video.gemini_video_io import (
    analyze_video_json_with_gemini,
    call_gemini_video_json,
    is_quota_error,
    wait_for_active_file,
)

logger = logging.getLogger(__name__)

ANALYSIS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "required": [
        "score", "issues", "visual_coherence", "subtitle_quality",
        "rhythm", "voice_expressiveness", "summary",
    ],
    "properties": {
        "score": {"type": "INTEGER"},
        "issues": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "type": {"type": "STRING"},
                    "severity": {"type": "STRING"},
                    "timestamp_s": {"type": "INTEGER"},
                    "description": {"type": "STRING"},
                },
            },
        },
        "visual_coherence": {"type": "INTEGER"},
        "subtitle_quality": {"type": "INTEGER"},
        "rhythm": {"type": "INTEGER"},
        "voice_expressiveness": {"type": "INTEGER"},
        "summary": {"type": "STRING"},
    },
}

ANALYST_PROMPT = """Analyse cette vidéo éducative et identifie tous les problèmes visuels et techniques.

Chaîne : {channel_name} | Thème : {theme} | Durée : {duration_s}s | Itération : {iteration}

Vérifie spécifiquement :

PROBLÈMES D'AFFICHAGE :
- Sous-titres mal positionnés, tronqués, illisibles ou avec fautes de frappe
- Textes superposés incorrectement sur les images
- Artefacts visuels, glitches, images corrompues

QUALITÉ VISUELLE :
- Pertinence des images par rapport à la narration (l'image montre-t-elle ce dont parle la voix ?)
- Répétition d'images identiques sans variation
- Qualité des images (floues, pixelisées, mal cadrées, anachronismes)
- Cohérence thématique des visuels

COHÉRENCE AUDIO-VISUELLE :
- Synchronisation narration / changements d'images
- Les transitions entre segments sont-elles fluides ?
- Le rythme des changements d'images est-il adapté au discours ?
- Changement visuel au moins toutes les 4 secondes (shorts) ?

EXPRESSIVITÉ VOCALE :
- La voix est-elle monotone sur toute la vidéo ?
- Y a-t-il une variation d'énergie entre le hook et la conclusion ?
- Manque-t-il d'emphase sur les mots importants ?

STRUCTURE :
- L'accroche des 30 premières secondes est-elle efficace ?
- La conclusion est-elle claire et mémorable ?
- Y a-t-il des silences trop longs ou des ruptures de rythme ?

Retourne UNIQUEMENT ce JSON valide (sans markdown, sans ```json) :
{{
  "score": 75,
  "issues": [
    {{"type": "subtitle", "severity": "high", "timestamp_s": 32, "description": "Sous-titre tronqué, le texte dépasse le cadre droit"}},
    {{"type": "visual", "severity": "medium", "timestamp_s": 145, "description": "Même image de cathédrale utilisée 3 fois consécutives sans variation"}}
  ],
  "visual_coherence": 18,
  "subtitle_quality": 22,
  "rhythm": 20,
  "voice_expressiveness": 7,
  "summary": "Résumé de l'analyse globale en 2-3 phrases"
}}

Règles :
- Si aucun problème détecté : issues = []
- severity ∈ ["low", "medium", "high"]
- type ∈ ["subtitle", "visual", "audio", "structure", "coherence", "dynamism"]
- timestamp_s : secondes approximatives dans la vidéo (0 si non applicable)
- score entre 0 et 100 (qualité globale observée)
- visual_coherence, subtitle_quality, rhythm : chacun entre 0 et 25
- voice_expressiveness : entre 0 et 10 (monotonie = score bas)
- description : maximum 120 caractères"""


@dataclass
class VideoAnalysis:
    score: int
    issues: list[dict[str, Any]]
    visual_coherence: int
    subtitle_quality: int
    rhythm: int
    summary: str
    voice_expressiveness: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "issues": self.issues,
            "visual_coherence": self.visual_coherence,
            "subtitle_quality": self.subtitle_quality,
            "rhythm": self.rhythm,
            "voice_expressiveness": self.voice_expressiveness,
            "summary": self.summary,
        }


async def analyze_video_with_gemini(
    video_path: Path,
    channel_name: str,
    theme: str,
    duration_s: float,
    iteration: int,
    api_key: str,
    model_name: str = "gemini-2.5-pro",
    fallback_model: str = "gemini-3.5-flash",
) -> VideoAnalysis:
    """Upload the video to Gemini File API and run visual analysis.
    Falls back to fallback_model if the primary model hits a quota/billing error.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError(
            "google-genai non installé — run: pip install google-genai"
        )

    prompt = ANALYST_PROMPT.format(
        channel_name=channel_name,
        theme=theme,
        duration_s=int(duration_s),
        iteration=iteration,
    )

    def _upload_and_analyze() -> dict[str, Any]:
        client = genai.Client(api_key=api_key)
        logger.info("Gemini : upload vidéo %s", video_path)
        uploaded = client.files.upload(
            file=str(video_path),
            config=types.UploadFileConfig(mime_type="video/mp4"),
        )
        uploaded = wait_for_active_file(client, types, uploaded)

        try:
            return call_gemini_video_json(
                client,
                types,
                model_name,
                uploaded,
                prompt,
                response_schema=ANALYSIS_RESPONSE_SCHEMA,
                label="video_analyst",
            )
        except Exception as primary_exc:
            if is_quota_error(primary_exc) and fallback_model and fallback_model != model_name:
                logger.warning(
                    "Gemini %s quota/crédit épuisé (%s) — fallback sur %s",
                    model_name,
                    primary_exc,
                    fallback_model,
                )
                return call_gemini_video_json(
                    client,
                    types,
                    fallback_model,
                    uploaded,
                    prompt,
                    response_schema=ANALYSIS_RESPONSE_SCHEMA,
                    label="video_analyst",
                )
            raise
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    data = await asyncio.to_thread(_upload_and_analyze)

    return VideoAnalysis(
        score=int(data.get("score", 0)),
        issues=data.get("issues", []),
        visual_coherence=int(data.get("visual_coherence", 0)),
        subtitle_quality=int(data.get("subtitle_quality", 0)),
        rhythm=int(data.get("rhythm", 0)),
        voice_expressiveness=int(data.get("voice_expressiveness", 0)),
        summary=data.get("summary", ""),
        raw=data,
    )


async def run_video_analysis(
    video_path: Path | str,
    channel_name: str,
    theme: str,
    duration_s: float,
    iteration: int,
    api_key: str,
) -> VideoAnalysis | None:
    """Entry point — returns None on any error so the pipeline can continue."""
    path = Path(video_path)
    if not path.exists():
        logger.warning("VideoAnalyst : fichier introuvable %s — analyse ignorée", path)
        return None
    try:
        return await analyze_video_with_gemini(
            path, channel_name, theme, duration_s, iteration, api_key
        )
    except Exception as e:
        logger.error("VideoAnalyst Gemini échoué (%s) — critique continuera sans analyse vidéo", e)
        return None
