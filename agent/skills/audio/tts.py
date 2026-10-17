from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent.core.config import settings
from agent.skills.audio.gemini_tts import (
    DEFAULT_GEMINI_LANGUAGE,
    DEFAULT_GEMINI_TTS_MODEL,
)
from agent.skills.video.ffmpeg_runtime import filter_thread_args, probe_duration, run_ffmpeg, thread_args

logger = logging.getLogger(__name__)



async def normalize_wav(
    src: Path, dst: Path, *, mastering: dict[str, Any] | None = None
) -> Path:
    """Convertit en WAV 48kHz 16bit avec mastering studio + loudnorm broadcast.

    `mastering=None` utilise la config globale (data/agent_config.json → audio_mastering).
    Quand le mastering est désactivé, seul le loudnorm est appliqué (non-régression).
    """
    from agent.skills.audio.mastering import build_audio_filter

    audio_filter = await build_audio_filter(mastering)
    cmd = [
        "ffmpeg", "-y",
        *filter_thread_args(),
        "-i", str(src),
        *thread_args(),
        "-ar", "48000",
        "-ac", "1",
        "-sample_fmt", "s16",
        "-af", audio_filter,
        str(dst),
    ]
    await run_ffmpeg(cmd, error_prefix="FFmpeg TTS convert error")
    return dst


def resolve_engine(
    requested: str | None,
    *,
    gemini_api_key: str | None = None,
    azure_speech_key: str | None = None,
    gcp_credentials_json: str | None = None,
) -> str:
    """Moteur effectif : les clés sont celles de l'utilisateur (None = moteur indisponible).

    Gemini est disponible avec une clé Gemini ou un compte de service GCP (Vertex AI).
    """
    engine = requested or settings.tts_engine or "azure"
    if engine == "azure" and not (azure_speech_key or "").strip():
        logger.warning("Azure Speech non configuré — fallback edge-tts")
        return "edge-tts"
    if engine == "gemini" and not (gemini_api_key or "").strip() and not (gcp_credentials_json or "").strip():
        logger.warning("Gemini TTS demandé sans clé Gemini ni compte Google Cloud — fallback azure/edge-tts")
        return resolve_engine(
            "azure",
            gemini_api_key=gemini_api_key,
            azure_speech_key=azure_speech_key,
        )
    return engine


async def generate_tts(
    text: str,
    output_path: Path,
    voice: str = "fr-FR-Vivienne:DragonHDLatestNeural",
    engine: str | None = None,
    delivery_style: dict[str, Any] | None = None,
    editorial_tone: str = "",
    tts_style: str = "narration-professional",
    tts_rate: str = "+0%",
    tts_pitch: str = "+0Hz",
    mood: str = "",
    insert_pauses: bool = True,
    comma_pauses: bool = False,
    *,
    gemini_model: str = DEFAULT_GEMINI_TTS_MODEL,
    gemini_language_code: str = DEFAULT_GEMINI_LANGUAGE,
    gemini_api_key: str | None = None,
    azure_speech_key: str | None = None,
    azure_speech_region: str | None = None,
    gcp_credentials_json: str | None = None,
    gcp_location: str | None = None,
    mastering: dict[str, Any] | None = None,
) -> tuple[float, str]:
    """Génère un fichier audio WAV depuis un texte. Retourne (durée_s, moteur_effectif).

    Gemini : clé Gemini d'abord, puis Vertex AI (`gemini-vertex`) si la clé est absente ou refusée.
    """
    resolved = resolve_engine(
        engine,
        gemini_api_key=gemini_api_key,
        azure_speech_key=azure_speech_key,
        gcp_credentials_json=gcp_credentials_json,
    )
    effective_gemini = (gemini_api_key or "").strip()
    effective_azure = (azure_speech_key or "").strip()
    effective_region = (azure_speech_region or settings.azure_speech_region).strip()

    if resolved == "gemini":
        from agent.core.vertex import gemini_key_refused
        from agent.skills.audio.gemini_tts import synthesize_gemini_tts, vertex_tts_target

        vertex = vertex_tts_target(gcp_credentials_json, gcp_location)
        common: dict[str, Any] = {
            "voice": voice,
            "language_code": gemini_language_code,
            "mood": mood,
            "editorial_tone": editorial_tone,
            "tts_style": tts_style,
            "mastering": mastering,
        }
        if effective_gemini:
            try:
                duration = await synthesize_gemini_tts(
                    text,
                    output_path,
                    model=gemini_model,
                    api_key=effective_gemini,
                    # Vertex en réserve : un quota épuisé ne mérite pas d'attendre les relances.
                    **({"transient_retries": 1} if vertex else {}),
                    **common,
                )
                return duration, "gemini"
            except Exception as exc:
                if vertex is None or not gemini_key_refused(exc):
                    raise
                logger.warning("Clé Gemini refusée (%s) — nouvel essai via Vertex AI", str(exc)[:120])
        if vertex is None:
            raise RuntimeError("Clé Gemini non configurée pour la synthèse TTS")
        duration = await synthesize_gemini_tts(text, output_path, vertex=vertex, **common)
        return duration, "gemini-vertex"

    if resolved == "azure":
        from agent.skills.audio.azure_tts import synthesize_ssml
        from agent.skills.audio.ssml_builder import build_azure_ssml

        ssml = build_azure_ssml(
            text,
            voice,
            delivery_style=delivery_style,
            mood=mood,
            editorial_tone=editorial_tone,
            default_style=tts_style,
            default_rate=tts_rate,
            default_pitch=tts_pitch,
            insert_pauses=insert_pauses,
            comma_pauses=comma_pauses,
        )
        duration = await synthesize_ssml(
            ssml,
            output_path,
            voice,
            subscription_key=effective_azure or None,
            region=effective_region,
            mastering=mastering,
        )
        return duration, "azure"

    duration = await _generate_edge_tts(
        text, output_path, voice, mastering=mastering, rate=tts_rate, pitch=tts_pitch
    )
    return duration, "edge-tts"


async def _generate_edge_tts(
    text: str,
    output_path: Path,
    voice: str,
    *,
    mastering: dict[str, Any] | None = None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> float:
    import edge_tts

    tmp_mp3 = output_path.with_suffix(".mp3")
    communicate = edge_tts.Communicate(text, voice, rate=rate or "+0%", pitch=pitch or "+0Hz")
    try:
        await communicate.save(str(tmp_mp3))
    except Exception as exc:
        raise RuntimeError(f"edge-tts échoué (voix={voice}): {exc}") from exc

    await normalize_wav(tmp_mp3, output_path, mastering=mastering)
    tmp_mp3.unlink(missing_ok=True)

    duration = await probe_duration(output_path)
    logger.debug("TTS edge généré : %.1f s → %s", duration, output_path)
    return duration
