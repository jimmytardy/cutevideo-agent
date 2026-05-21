from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

NARRATION_LEVEL = "0"
MUSIC_LEVEL = "-20dB"


async def mix_narration_with_music(
    narration_path: Path,
    music_path: Path | None,
    output_path: Path,
    duck_music: bool = True,
) -> None:
    """Mélange narration + musique de fond avec ducking."""
    if music_path is None or not music_path.exists():
        await _copy_audio(narration_path, output_path)
        return

    if duck_music:
        filter_complex = (
            f"[0:a]volume={NARRATION_LEVEL}[narration];"
            f"[1:a]volume={MUSIC_LEVEL}[music];"
            f"[narration][music]amix=inputs=2:duration=first[out]"
        )
    else:
        filter_complex = (
            f"[0:a][1:a]amix=inputs=2:duration=first[out]"
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


async def _copy_audio(src: Path, dst: Path) -> None:
    import shutil
    await asyncio.get_event_loop().run_in_executor(None, shutil.copy2, src, dst)


async def _run(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Audio mixer FFmpeg error: {stderr.decode()[-500:]}")
