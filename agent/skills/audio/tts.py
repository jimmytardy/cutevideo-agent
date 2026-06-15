from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agent.core.config import settings
from agent.skills.audio.gemini_tts import (
    DEFAULT_GEMINI_LANGUAGE,
    DEFAULT_GEMINI_TTS_MODEL,
    DEFAULT_GEMINI_VOICE,
)

logger = logging.getLogger(__name__)

GeminiTtsApplyTo = Literal["off", "shorts", "long", "both"]

_NOT_PASSED = object()


@dataclass(frozen=True)
class ResolvedTtsSettings:
    engine: str
    voice: str
    gemini_model: str = DEFAULT_GEMINI_TTS_MODEL
    gemini_language_code: str = DEFAULT_GEMINI_LANGUAGE
    gemini_api_key: str | None = None
    azure_speech_key: str | None = None
    azure_speech_region: str | None = None


def _resolved_gemini_key(gemini_api_key: str | None | object) -> str:
    if gemini_api_key is _NOT_PASSED:
        return (settings.google_gemini_api_key or "").strip()
    return (gemini_api_key or "").strip() if gemini_api_key is not None else ""


def _resolved_azure_key(azure_speech_key: str | None | object) -> str:
    if azure_speech_key is _NOT_PASSED:
        return (settings.azure_speech_key or "").strip()
    return (azure_speech_key or "").strip() if azure_speech_key is not None else ""


def _resolved_azure_region(azure_speech_region: str | None | object) -> str:
    if azure_speech_region is _NOT_PASSED:
        return settings.azure_speech_region
    return (azure_speech_region or settings.azure_speech_region).strip()


async def normalize_wav(src: Path, dst: Path) -> Path:
    """Convertit en WAV 48kHz 16bit normalisé (-16 LUFS broadcast)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-ar", "48000",
        "-ac", "1",
        "-sample_fmt", "s16",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        str(dst),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg TTS convert error: {stderr.decode()[-500:]}")
    return dst


async def probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    raw = stdout.decode().strip()
    if not raw:
        raise RuntimeError(
            f"ffprobe n'a retourné aucune durée pour {path} "
            f"(code {proc.returncode}): {stderr.decode()[-300:]}"
        )
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Durée invalide retournée par ffprobe pour {path}: {raw!r}") from exc


def resolve_engine(
    requested: str | None,
    *,
    gemini_api_key: str | None | object = _NOT_PASSED,
    azure_speech_key: str | None | object = _NOT_PASSED,
) -> str:
    engine = requested or settings.tts_engine or "azure"
    azure_key = _resolved_azure_key(azure_speech_key)
    gemini_key = _resolved_gemini_key(gemini_api_key)
    if engine == "azure" and not azure_key:
        logger.warning("Azure Speech non configuré — fallback edge-tts")
        return "edge-tts"
    if engine == "gemini" and not gemini_key:
        logger.warning("Gemini TTS demandé mais clé Gemini absente — fallback azure/edge-tts")
        return resolve_engine(
            "azure",
            gemini_api_key=gemini_api_key,
            azure_speech_key=azure_speech_key,
        )
    return engine


def should_use_gemini_tts(
    gemini_apply_to: str,
    *,
    is_short: bool,
    gemini_api_key: str | None | object = _NOT_PASSED,
) -> bool:
    if gemini_apply_to == "off":
        return False
    if not _resolved_gemini_key(gemini_api_key):
        return False
    if gemini_apply_to == "both":
        return True
    if gemini_apply_to == "shorts":
        return is_short
    if gemini_apply_to == "long":
        return not is_short
    return False


def resolve_tts_settings(
    *,
    default_engine: str,
    default_voice: str,
    gemini_apply_to: str = "off",
    gemini_voice: str = DEFAULT_GEMINI_VOICE,
    gemini_model: str = DEFAULT_GEMINI_TTS_MODEL,
    gemini_language_code: str = DEFAULT_GEMINI_LANGUAGE,
    is_short: bool = False,
    gemini_api_key: str | None | object = _NOT_PASSED,
    azure_speech_key: str | None | object = _NOT_PASSED,
    azure_speech_region: str | None | object = _NOT_PASSED,
) -> ResolvedTtsSettings:
    """Résout le moteur et la voix effectifs selon le format vidéo et les clés API."""
    effective_gemini = _resolved_gemini_key(gemini_api_key)
    effective_azure = _resolved_azure_key(azure_speech_key)
    effective_region = _resolved_azure_region(azure_speech_region)
    gemini_key_arg = None if gemini_api_key is _NOT_PASSED else gemini_api_key
    azure_key_arg = None if azure_speech_key is _NOT_PASSED else azure_speech_key

    if should_use_gemini_tts(
        gemini_apply_to, is_short=is_short, gemini_api_key=gemini_api_key
    ):
        return ResolvedTtsSettings(
            engine="gemini",
            voice=gemini_voice,
            gemini_model=gemini_model,
            gemini_language_code=gemini_language_code,
            gemini_api_key=effective_gemini or None,
            azure_speech_key=effective_azure or None,
            azure_speech_region=effective_region,
        )

    if gemini_apply_to != "off" and not effective_gemini:
        scope = "shorts" if is_short else "long"
        logger.warning(
            "Gemini TTS activé pour %s (apply_to=%s) mais clé Gemini absente — "
            "utilisation du moteur par défaut (%s)",
            scope,
            gemini_apply_to,
            default_engine,
        )

    return ResolvedTtsSettings(
        engine=resolve_engine(
            default_engine,
            gemini_api_key=gemini_api_key,
            azure_speech_key=azure_speech_key,
        ),
        voice=default_voice,
        gemini_model=gemini_model,
        gemini_language_code=gemini_language_code,
        gemini_api_key=effective_gemini or None,
        azure_speech_key=effective_azure or None,
        azure_speech_region=effective_region,
    )


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
    *,
    gemini_model: str = DEFAULT_GEMINI_TTS_MODEL,
    gemini_language_code: str = DEFAULT_GEMINI_LANGUAGE,
    gemini_api_key: str | None | object = _NOT_PASSED,
    azure_speech_key: str | None | object = _NOT_PASSED,
    azure_speech_region: str | None | object = _NOT_PASSED,
) -> tuple[float, str]:
    """Génère un fichier audio WAV depuis un texte. Retourne (durée_s, moteur_effectif)."""
    resolved = resolve_engine(
        engine,
        gemini_api_key=gemini_api_key,
        azure_speech_key=azure_speech_key,
    )
    effective_gemini = _resolved_gemini_key(gemini_api_key)
    effective_azure = _resolved_azure_key(azure_speech_key)
    effective_region = _resolved_azure_region(azure_speech_region)

    if resolved == "gemini":
        from agent.skills.audio.gemini_tts import synthesize_gemini_tts

        if not effective_gemini:
            raise RuntimeError("Clé Gemini non configurée pour la synthèse TTS")
        duration = await synthesize_gemini_tts(
            text,
            output_path,
            voice=voice,
            model=gemini_model,
            language_code=gemini_language_code,
            mood=mood,
            editorial_tone=editorial_tone,
            tts_style=tts_style,
            api_key=effective_gemini,
        )
        return duration, "gemini"

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
        )
        duration = await synthesize_ssml(
            ssml,
            output_path,
            voice,
            subscription_key=effective_azure or None,
            region=effective_region,
        )
        return duration, "azure"

    duration = await _generate_edge_tts(text, output_path, voice)
    return duration, "edge-tts"


async def _generate_edge_tts(text: str, output_path: Path, voice: str) -> float:
    import edge_tts

    tmp_mp3 = output_path.with_suffix(".mp3")
    communicate = edge_tts.Communicate(text, voice)
    try:
        await communicate.save(str(tmp_mp3))
    except Exception as exc:
        raise RuntimeError(f"edge-tts échoué (voix={voice}): {exc}") from exc

    await normalize_wav(tmp_mp3, output_path)
    tmp_mp3.unlink(missing_ok=True)

    duration = await probe_duration(output_path)
    logger.debug("TTS edge généré : %.1f s → %s", duration, output_path)
    return duration
