"""Registre des sous-processus OS pour arrêt propre (SIGTERM / annulation pipeline)."""

from __future__ import annotations

import asyncio
import logging
from asyncio.subprocess import Process

logger = logging.getLogger(__name__)

_registered: set[Process] = set()


def register(proc: Process) -> None:
    _registered.add(proc)


def unregister(proc: Process) -> None:
    _registered.discard(proc)


async def terminate_proc(proc: Process, *, grace_s: float = 2.0) -> None:
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


async def kill_all(*, grace_s: float = 2.0) -> None:
    for proc in list(_registered):
        try:
            await terminate_proc(proc, grace_s=grace_s)
        except ProcessLookupError:
            pass
        except Exception as exc:
            logger.warning("Erreur kill subprocess pid=%s : %s", proc.pid, exc)
        finally:
            unregister(proc)
