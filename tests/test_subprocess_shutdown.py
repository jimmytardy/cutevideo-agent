"""Tests arrêt propre des sous-processus."""

from __future__ import annotations

import asyncio
import sys

import pytest

from agent.core.subprocess_registry import kill_all, register, terminate_proc, unregister


@pytest.mark.asyncio
async def test_terminate_proc_kills_running_subprocess() -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    register(proc)
    try:
        await terminate_proc(proc, grace_s=1.0)
        assert proc.returncode is not None
    finally:
        unregister(proc)


@pytest.mark.asyncio
async def test_kill_all_is_idempotent() -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    register(proc)
    await kill_all()
    await kill_all()
    assert proc.returncode is not None


@pytest.mark.asyncio
async def test_run_ffmpeg_kills_subprocess_on_cancel() -> None:
    from agent.skills.video import ffmpeg_runtime

    ffmpeg_runtime._FFMPEG_SEMAPHORE = None

    async def _run_long_ffmpeg() -> None:
        await ffmpeg_runtime.run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc",
                "-t",
                "120",
                "-f",
                "null",
                "-",
            ],
            error_prefix="test",
        )

    task = asyncio.create_task(_run_long_ffmpeg())
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await kill_all()
