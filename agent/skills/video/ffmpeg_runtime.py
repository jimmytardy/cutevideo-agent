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
import re
from pathlib import Path

from agent.core.env import env_int

logger = logging.getLogger(__name__)


def ffmpeg_threads() -> int:
    """Nombre max de threads par process ffmpeg (FFMPEG_THREADS, défaut 2)."""
    return env_int("FFMPEG_THREADS", 2, minimum=1)


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


async def run_ffmpeg(
    cmd: list[str], *, error_prefix: str = "FFmpeg error", check: bool = True, timeout_s: float | None = None
) -> str:
    """Exécute ffmpeg en série (sémaphore global) et renvoie son stderr ; lève en cas d'échec
    (sauf ``check=False``, pour les mesures qui lisent le stderr).

    Garantit qu'un seul process ffmpeg s'exécute à la fois dans tout le
    process Python, même si l'appelant fait du fan-out (asyncio.gather).
    Tue le subprocess si la tâche asyncio parente est annulée, ou après
    ``timeout_s`` secondes (RuntimeError) : sans cela un ffmpeg qui boucle sur
    une source illisible bloquerait tous les encodages suivants.
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
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout_s)
        except TimeoutError:
            # Un ffmpeg bloqué a souvent son stderr saturé (plus rien ne le lit) : SIGTERM resterait sans effet.
            await terminate_proc(proc, grace_s=0.5)
            raise RuntimeError(
                f"{error_prefix}: ffmpeg interrompu après {timeout_s:.0f} s (source illisible ou boucle infinie ?)"
            ) from None
        except asyncio.CancelledError:
            await terminate_proc(proc)
            raise
        finally:
            unregister(proc)
    text = stderr.decode(errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError(f"{error_prefix}: {text[-2000:]}")
    return text


async def probe_duration(path: Path) -> float:
    """Durée (s) d'un fichier audio/vidéo via ffprobe (sonde légère, hors sémaphore)."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    raw = stdout.decode().strip()
    if not raw:
        raise RuntimeError(
            f"ffprobe n'a retourné aucune durée pour {path} "
            f"(code {proc.returncode}): {stderr.decode()[-300:]}"
        )
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Durée invalide retournée par ffprobe pour {path}: {raw!r}") from exc


async def measure_loudness(path: Path) -> tuple[float | None, float | None]:
    """(loudness intégrée LUFS, crête dBFS) de la 1re piste audio via le filtre ebur128.

    Décode tout le fichier : passe par la sémaphore et les plafonds de threads.
    """
    err = await run_ffmpeg(
        [
            "ffmpeg", "-nostats", *filter_thread_args(), "-i", str(path), *thread_args(),
            "-map", "0:a:0", "-af", "ebur128=peak=sample", "-f", "null", "-",
        ],
        check=False,
    )
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    peak = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)
    return (float(lufs[-1]) if lufs else None, float(peak[-1]) if peak else None)
