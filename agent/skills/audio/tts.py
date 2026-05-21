from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def generate_tts(
    text: str,
    output_path: Path,
    voice: str = "fr-FR-HenriNeural",
    engine: str = "edge-tts",
) -> float:
    """Génère un fichier audio WAV depuis un texte via edge-tts ou Coqui."""
    if engine == "edge-tts":
        return await _generate_edge_tts(text, output_path, voice)
    raise ValueError(f"Moteur TTS inconnu : {engine}")


async def _generate_edge_tts(text: str, output_path: Path, voice: str) -> float:
    """Génère l'audio avec edge-tts (voix Microsoft Neural gratuite)."""
    import edge_tts

    tmp_mp3 = output_path.with_suffix(".mp3")
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(tmp_mp3))

    wav_path = await _convert_to_wav(tmp_mp3, output_path)
    tmp_mp3.unlink(missing_ok=True)

    duration = await _probe_duration(wav_path)
    logger.debug("TTS généré : %.1f s → %s", duration, output_path)
    return duration


async def _convert_to_wav(src: Path, dst: Path) -> Path:
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


async def _probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0
