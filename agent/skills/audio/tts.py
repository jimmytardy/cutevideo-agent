from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from agent.core.config import settings

logger = logging.getLogger(__name__)


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


def resolve_engine(requested: str | None) -> str:
    engine = requested or settings.tts_engine or "azure"
    if engine == "azure" and not settings.azure_speech_key:
        logger.warning("Azure Speech non configuré — fallback edge-tts")
        return "edge-tts"
    return engine


async def generate_tts(
    text: str,
    output_path: Path,
    voice: str = "fr-FR-HenriNeural",
    engine: str | None = None,
    delivery_style: dict[str, Any] | None = None,
    editorial_tone: str = "",
    tts_style: str = "narration-professional",
    tts_rate: str = "+0%",
    tts_pitch: str = "+0Hz",
) -> float:
    """Génère un fichier audio WAV depuis un texte."""
    resolved = resolve_engine(engine)
    if resolved == "azure":
        from agent.skills.audio.azure_tts import synthesize_ssml
        from agent.skills.audio.ssml_builder import build_azure_ssml

        ssml = build_azure_ssml(
            text,
            voice,
            delivery_style=delivery_style,
            editorial_tone=editorial_tone,
            default_style=tts_style,
            default_rate=tts_rate,
            default_pitch=tts_pitch,
        )
        return await synthesize_ssml(ssml, output_path, voice)
    return await _generate_edge_tts(text, output_path, voice)


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
