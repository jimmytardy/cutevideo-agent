from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


async def mix_narration_with_music(
    narration_path: Path,
    music_path: Path | None,
    output_path: Path,
    duck_music: bool = True,
    music_volume: float = 0.06,
) -> None:
    """Mélange narration + musique de fond avec ducking optionnel."""
    if music_path is None or not music_path.exists():
        await asyncio.get_running_loop().run_in_executor(None, shutil.copy2, narration_path, output_path)
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

    from agent.skills.video.ffmpeg_runtime import run_ffmpeg, thread_args

    cmd = [
        "ffmpeg", "-y",
        "-i", str(narration_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        *thread_args(),
        "-c:a", "aac", "-ar", "48000",
        str(output_path),
    ]
    await run_ffmpeg(cmd, error_prefix="Audio mixer FFmpeg error")
    logger.debug("Mix audio → %s", output_path)
