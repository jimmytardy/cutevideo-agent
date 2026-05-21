from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def transcribe_to_srt(
    audio_paths: list[Path],
    output_srt: Path,
    model_name: str = "large-v3",
) -> None:
    """Transcrit une liste de fichiers audio en fichier .srt via Whisper."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _transcribe_sync, audio_paths, output_srt, model_name)


def _transcribe_sync(
    audio_paths: list[Path],
    output_srt: Path,
    model_name: str,
) -> None:
    import whisper

    model = whisper.load_model(model_name)
    all_segments: list[dict] = []
    time_offset = 0.0

    for audio_path in audio_paths:
        if not audio_path.exists():
            logger.warning("Fichier audio introuvable : %s", audio_path)
            continue

        result = model.transcribe(str(audio_path), language="fr", word_timestamps=True)
        for seg in result.get("segments", []):
            all_segments.append({
                "start": seg["start"] + time_offset,
                "end": seg["end"] + time_offset,
                "text": seg["text"].strip(),
            })

        duration = _get_audio_duration(audio_path)
        time_offset += duration

    srt_content = _build_srt(all_segments)
    output_srt.write_text(srt_content, encoding="utf-8")
    logger.info("SRT généré : %d segments → %s", len(all_segments), output_srt)


def _build_srt(segments: list[dict]) -> str:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        start = _seconds_to_srt_time(seg["start"])
        end = _seconds_to_srt_time(seg["end"])
        lines.append(f"{i}\n{start} --> {end}\n{seg['text']}\n")
    return "\n".join(lines)


def _seconds_to_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _get_audio_duration(path: Path) -> float:
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0
