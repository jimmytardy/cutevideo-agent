from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class WordSegment:
    word: str
    start: float
    end: float


async def transcribe_to_words(
    audio_paths: list[Path],
    model_name: str = "large-v3",
    language: str = "fr",
) -> list[WordSegment]:
    """Transcrit une liste de fichiers audio en segments mot-à-mot via Whisper."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _transcribe_words_sync, audio_paths, model_name, language
    )


async def transcribe_to_srt(
    audio_paths: list[Path],
    output_srt: Path,
    model_name: str = "large-v3",
    language: str = "fr",
) -> None:
    """Transcrit une liste de fichiers audio en fichier .srt via Whisper."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _transcribe_srt_sync, audio_paths, output_srt, model_name, language
    )


def _transcribe_words_sync(
    audio_paths: list[Path],
    model_name: str,
    language: str,
) -> list[WordSegment]:
    _, all_words = _transcribe_internal(audio_paths, model_name, language)
    return all_words


def _transcribe_srt_sync(
    audio_paths: list[Path],
    output_srt: Path,
    model_name: str,
    language: str,
) -> None:
    all_segments, _ = _transcribe_internal(audio_paths, model_name, language)
    srt_content = _build_srt(all_segments)
    output_srt.write_text(srt_content, encoding="utf-8")
    logger.info("SRT généré : %d segments → %s", len(all_segments), output_srt)


def _transcribe_internal(
    audio_paths: list[Path],
    model_name: str,
    language: str,
) -> tuple[list[dict], list[WordSegment]]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    all_segments: list[dict] = []
    all_words: list[WordSegment] = []
    time_offset = 0.0

    for audio_path in audio_paths:
        if not audio_path.exists():
            logger.warning("Fichier audio introuvable : %s", audio_path)
            continue

        segments, _ = model.transcribe(
            str(audio_path), language=language, word_timestamps=True
        )
        for seg in segments:
            seg_start = seg.start + time_offset
            seg_end = seg.end + time_offset
            text = seg.text.strip()
            if text:
                all_segments.append({"start": seg_start, "end": seg_end, "text": text})

            if seg.words:
                for w in seg.words:
                    word = w.word.strip()
                    if word:
                        all_words.append(
                            WordSegment(
                                word=word,
                                start=w.start + time_offset,
                                end=w.end + time_offset,
                            )
                        )
            elif text:
                all_words.append(
                    WordSegment(word=text, start=seg_start, end=seg_end)
                )

        time_offset += _get_audio_duration(audio_path)

    logger.info(
        "Whisper : %d segments, %d mots transcrits",
        len(all_segments),
        len(all_words),
    )
    return all_segments, all_words


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
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


async def extract_audio_from_video(video_path: Path, output_wav: Path) -> Path | None:
    """Extrait la piste audio d'une vidéo en WAV pour transcription Whisper."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(output_wav),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not output_wav.exists():
        logger.warning(
            "Extraction audio vidéo échouée pour %s : %s",
            video_path.name,
            stderr.decode()[-300:],
        )
        return None
    return output_wav


async def transcribe_video_to_words(
    video_path: Path,
    output_dir: Path,
    model_name: str = "large-v3",
    language: str = "fr",
) -> list[WordSegment]:
    """Transcrit la piste audio muxée d'une vidéo (fallback sans fichiers TTS)."""
    wav_path = output_dir / f"{video_path.stem}_extract.wav"
    extracted = await extract_audio_from_video(video_path, wav_path)
    if not extracted:
        return []
    return await transcribe_to_words([extracted], model_name=model_name, language=language)
