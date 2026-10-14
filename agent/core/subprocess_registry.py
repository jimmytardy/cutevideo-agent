"""Registre des sous-processus OS pour arrêt propre (SIGTERM / annulation pipeline)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from asyncio.subprocess import Process

logger = logging.getLogger(__name__)

_registered: set[Process] = set()


def register(proc: Process) -> None:
    _registered.add(proc)


def unregister(proc: Process) -> None:
    _registered.discard(proc)


def _is_group_leader(proc: Process) -> bool:
    try:
        return os.getpgid(proc.pid) == proc.pid
    except ProcessLookupError:
        return False


async def terminate_proc(proc: Process, *, grace_s: float = 2.0) -> None:
    """Arrête le process et, s'il mène son propre groupe (`start_new_session=True`), tous ses
    descendants : sinon outils, ffmpeg et Chromium survivraient à l'annulation."""
    if proc.returncode is not None:
        return
    leader = _is_group_leader(proc)

    def send(sig: int) -> None:
        try:
            os.killpg(proc.pid, sig) if leader else proc.send_signal(sig)
        except ProcessLookupError:
            pass

    send(signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace_s)
    except TimeoutError:
        send(signal.SIGKILL)
        await proc.wait()
    if leader:
        send(signal.SIGKILL)  # le leader peut sortir avant ses descendants


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
