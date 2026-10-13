"""L'arrêt d'un process lancé dans son propre groupe tue aussi ses descendants."""

from __future__ import annotations

import asyncio
import os
import sys

from agent.core.subprocess_registry import terminate_proc


def test_terminate_kills_grandchildren() -> None:
    async def scenario() -> int:
        # Le petit-enfant ignore SIGTERM et survivrait à un simple proc.terminate().
        code = (
            "import subprocess, sys, time; "
            "p = subprocess.Popen([sys.executable, '-c', "
            "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']); "
            "print(p.pid, flush=True); time.sleep(60)"
        )
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code, stdout=asyncio.subprocess.PIPE, start_new_session=True
        )
        assert proc.stdout is not None
        grandchild = int((await proc.stdout.readline()).decode())
        await terminate_proc(proc, grace_s=1)
        await asyncio.sleep(0.3)
        return grandchild

    grandchild = asyncio.run(scenario())
    try:
        os.kill(grandchild, 0)
    except ProcessLookupError:
        return
    # Zombie possible tant que init ne l'a pas récolté : vérifier l'état.
    with open(f"/proc/{grandchild}/stat") as fh:
        assert fh.read().split()[2] == "Z", "le petit-enfant a survécu à l'arrêt"
