"""Garde-fous CPU/RAM partagés par tous les encodages ffmpeg.

Contexte : sur une machine à RAM/CPU limités, un encodage libx264 sature par
défaut TOUS les cœurs (un thread par cœur logique). De plus, certains agents
peuvent lancer plusieurs ffmpeg en parallèle (asyncio.gather). On centralise
donc ici :

- ``FFMPEG_THREADS`` : plafond de cœurs par process ffmpeg (défaut 2).
- ``FFMPEG_PRESET``  : preset libx264 par défaut (défaut "medium", mettre
  "fast" pour revenir au comportement léger d'avant).
- un sémaphore global (=1) garantissant qu'UN SEUL ffmpeg tourne à la fois
  dans tout le process, quel que soit l'agent appelant.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def ffmpeg_threads() -> int:
    """Nombre max de threads par process ffmpeg (FFMPEG_THREADS, défaut 2)."""
    try:
        return max(1, int(os.getenv("FFMPEG_THREADS", "2")))
    except ValueError:
        return 2


def ffmpeg_preset(default: str = "medium") -> str:
    """Preset libx264 (FFMPEG_PRESET, sinon ``default``)."""
    return os.getenv("FFMPEG_PRESET", default)


def thread_args() -> list[str]:
    """Arguments ``-threads N`` à insérer dans toute commande ffmpeg.

    Attention : ``-threads`` ne plafonne QUE l'encodeur (libx264). Le filtrage
    (``-vf`` / ``-filter_complex``) utilise par défaut ``-filter_threads`` =
    nombre de cœurs logiques → satured tous les cœurs malgré ``-threads``.
    Pour toute commande avec filtres lourds (monteur, ken burns), ajouter aussi
    ``filter_thread_args()``.
    """
    return ["-threads", str(ffmpeg_threads())]


def filter_thread_args() -> list[str]:
    """Plafonne les threads de filtrage (``-vf`` ET ``-filter_complex``).

    Options globales : doivent être placées AVANT les entrées (juste après
    ``ffmpeg -y``). Indispensable pour le monteur, dont le coût est dominé par
    le ``-filter_complex`` (zoompan/ken burns, scale, overlays, color grade).
    """
    n = str(ffmpeg_threads())
    return ["-filter_threads", n, "-filter_complex_threads", n]


_FFMPEG_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _FFMPEG_SEMAPHORE
    if _FFMPEG_SEMAPHORE is None:
        _FFMPEG_SEMAPHORE = asyncio.Semaphore(1)
    return _FFMPEG_SEMAPHORE


async def run_ffmpeg(cmd: list[str], *, error_prefix: str = "FFmpeg error") -> None:
    """Exécute ffmpeg en série (sémaphore global) ; lève en cas d'échec.

    Garantit qu'un seul process ffmpeg s'exécute à la fois dans tout le
    process Python, même si l'appelant fait du fan-out (asyncio.gather).
    Tue le subprocess si la tâche asyncio parente est annulée.
    """
    from agent.core.subprocess_registry import register, terminate_proc, unregister

    async with _get_semaphore():
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        register(proc)
        stderr = b""
        try:
            _, stderr = await proc.communicate()
        except asyncio.CancelledError:
            await terminate_proc(proc)
            raise
        finally:
            unregister(proc)
    if proc.returncode != 0:
        raise RuntimeError(f"{error_prefix}: {stderr.decode()[-2000:]}")
