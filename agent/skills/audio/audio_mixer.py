from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MUSIC_VOLUME = 0.08
CROSSFADE_DURATION = 2.0


def load_audio_mix_config() -> dict[str, Any]:
    from agent.core.config import load_agent_config

    cfg = load_agent_config().get("audio_mix", {})
    return {
        "music_volume_with_voice": float(cfg.get("music_volume_with_voice", 0.06)),
        "music_volume_ambient_only": float(cfg.get("music_volume_ambient_only", 0.04)),
        "music_volume_no_voice": float(cfg.get("music_volume_no_voice", 0.10)),
        "ducking_enabled": bool(cfg.get("ducking_enabled", True)),
    }


def resolve_music_volume(
    has_narration: bool,
    has_ambient: bool,
    cfg: dict[str, Any] | None = None,
) -> float:
    mix_cfg = cfg or load_audio_mix_config()
    if has_narration:
        return mix_cfg["music_volume_with_voice"]
    if has_ambient:
        return mix_cfg["music_volume_ambient_only"]
    return mix_cfg["music_volume_no_voice"]


def _build_mix_filter(
    music_volume: float,
    fade_start: float,
    duck_narration: bool,
) -> str:
    if duck_narration:
        return (
            f"[1:a]volume={music_volume},afade=t=out:st={fade_start:.2f}:d=3[music];"
            "[music][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=200:release=1000[ducked];"
            "[0:a][ducked]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    return (
        f"[1:a]volume={music_volume},afade=t=out:st={fade_start:.2f}:d=3[music];"
        "[0:a][music]amix=inputs=2:duration=first:normalize=0[aout]"
    )


async def mix_narration_with_music(
    narration_path: Path,
    music_path: Path | None,
    output_path: Path,
    duck_music: bool = True,
    music_volume: float = 0.06,
) -> None:
    """Mélange narration + musique de fond avec ducking optionnel."""
    if music_path is None or not music_path.exists():
        await _copy_audio(narration_path, output_path)
        return

    if duck_music:
        filter_complex = (
            f"[1:a]volume={music_volume}[music];"
            "[music][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=200:release=1000[ducked];"
            "[0:a][ducked]amix=inputs=2:duration=first:normalize=0[out]"
        )
    else:
        filter_complex = (
            f"[1:a]volume={music_volume}[music];"
            "[0:a][music]amix=inputs=2:duration=first:normalize=0[out]"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(narration_path),
        "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "aac", "-ar", "48000",
        str(output_path),
    ]
    await _run(cmd)
    logger.debug("Mix audio → %s", output_path)


async def strip_video_audio(input_path: Path, output_path: Path) -> None:
    """Supprime la piste audio d'un fichier vidéo (garde uniquement la vidéo)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", "copy",
        "-an",
        str(output_path),
    ]
    await _run(cmd)
    logger.debug("Audio supprimé : %s → %s", input_path.name, output_path.name)


async def mix_multi_segment_music(
    video_path: Path,
    mood_blocks: list[dict],
    output_path: Path,
    music_volume: float = MUSIC_VOLUME,
    duck_narration: bool = False,
) -> bool:
    """Mixe de la musique par blocs de mood avec crossfade entre transitions."""
    from agent.skills.audio.music_selector import select_music_for_mood
    from agent.skills.audio.music_fetcher import fetch_music_for_mood

    if not mood_blocks:
        import shutil
        await asyncio.get_event_loop().run_in_executor(None, shutil.copy2, video_path, output_path)
        return False

    import ffmpeg

    try:
        probe = ffmpeg.probe(str(video_path))
        has_audio = any(s.get("codec_type") == "audio" for s in probe.get("streams", []))
    except Exception as exc:
        logger.warning("Mix musique ignoré — sonde vidéo échouée : %s", exc)
        import shutil
        await asyncio.get_event_loop().run_in_executor(None, shutil.copy2, video_path, output_path)
        return False

    if not has_audio:
        logger.warning("Mix musique ignoré — pas de piste audio dans %s", video_path.name)
        import shutil
        await asyncio.get_event_loop().run_in_executor(None, shutil.copy2, video_path, output_path)
        return False

    blocks_with_music: list[tuple[Path, float, float]] = []
    for block in mood_blocks:
        mood = block["mood"]
        start_s = float(block["start_s"])
        duration_s = float(block["duration_s"])

        music = select_music_for_mood(mood)
        if not music:
            music = await fetch_music_for_mood(mood, output_dir=Path("./tmp/music"))
        if music:
            blocks_with_music.append((music, start_s, duration_s))

    if not blocks_with_music:
        logger.warning("Aucune musique trouvée pour les blocs de mood, vidéo inchangée")
        import shutil
        await asyncio.get_event_loop().run_in_executor(None, shutil.copy2, video_path, output_path)
        return False

    cmd = ["ffmpeg", "-y", "-i", str(video_path)]
    for music_path, _, _ in blocks_with_music:
        cmd += ["-stream_loop", "-1", "-i", str(music_path)]

    filter_parts: list[str] = []
    music_labels: list[str] = []

    for idx, (_, start_s, duration_s) in enumerate(blocks_with_music):
        input_idx = idx + 1
        label = f"[m{idx}]"
        delay_ms = int(start_s * 1000)
        fade_out_st = max(0.0, duration_s - CROSSFADE_DURATION)

        filters = [
            f"atrim=duration={duration_s:.3f}",
            "aformat=channel_layouts=stereo",
            f"volume={music_volume}",
        ]
        if start_s > 0:
            filters.append(f"afade=t=in:st=0:d={min(CROSSFADE_DURATION, duration_s / 2):.2f}")
        filters.append(f"afade=t=out:st={fade_out_st:.2f}:d={min(CROSSFADE_DURATION, duration_s / 2):.2f}")
        filters.append(f"adelay={delay_ms}|{delay_ms}")

        filter_parts.append(f"[{input_idx}:a]{','.join(filters)}{label}")
        music_labels.append(label)

    if len(music_labels) == 1:
        bed_label = music_labels[0]
    else:
        bed_label = "[musicbed]"
        filter_parts.append(
            f"{''.join(music_labels)}amix=inputs={len(music_labels)}:duration=longest:normalize=0{bed_label}"
        )

    if duck_narration:
        filter_parts.append(
            f"{bed_label}[0:a]sidechaincompress=threshold=0.02:ratio=8:attack=200:release=1000[ducked]"
        )
        filter_parts.append(
            "[0:a][ducked]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    else:
        filter_parts.append(
            f"[0:a]{bed_label}amix=inputs=2:duration=first:normalize=0[aout]"
        )

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run(cmd)
    logger.info("Mix multi-mood terminé (%d blocs) → %s", len(blocks_with_music), output_path)
    return True


async def _copy_audio(src: Path, dst: Path) -> None:
    import shutil
    await asyncio.get_event_loop().run_in_executor(None, shutil.copy2, src, dst)


async def _run(cmd: list[str]) -> None:
    from agent.skills.video.ffmpeg_runtime import run_ffmpeg

    await run_ffmpeg(cmd, error_prefix="Audio mixer FFmpeg error")
