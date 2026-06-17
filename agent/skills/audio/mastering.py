from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Preset « voice-studio » : chaîne légère de mastering voix appliquée AVANT le loudnorm
# final. Ordre studio classique : nettoyage bas → EQ → de-esser → compression.
DEFAULT_MASTERING: dict[str, Any] = {
    "enabled": True,
    "preset": "voice-studio",
    "highpass_hz": 80,
    "deesser": True,
    "compressor": {
        "threshold_db": -18,
        "ratio": 3,
        "attack_ms": 15,
        "release_ms": 120,
        "makeup_db": 2,
    },
    "eq": [
        {"f": 200, "g": -2, "w": 1},
        {"f": 3000, "g": 2, "w": 2},
    ],
}

# Cache des probes de disponibilité de filtres ffmpeg (clé = nom du filtre).
_filter_cache: dict[str, bool] = {}


def load_audio_mastering_config() -> dict[str, Any]:
    """Charge la config de mastering globale (data/agent_config.json → audio_mastering)."""
    from agent.core.config import load_agent_config

    cfg = dict(load_agent_config().get("audio_mastering", {}) or {})
    merged: dict[str, Any] = {**DEFAULT_MASTERING, **cfg}
    merged["compressor"] = {
        **DEFAULT_MASTERING["compressor"],
        **(cfg.get("compressor") or {}),
    }
    if "eq" not in cfg:
        merged["eq"] = [dict(band) for band in DEFAULT_MASTERING["eq"]]
    return merged


def build_mastering_chain(
    cfg: dict[str, Any], *, deesser_available: bool = True
) -> list[str]:
    """Construit la liste de filtres ffmpeg de mastering (hors loudnorm final).

    Retourne une liste vide si le mastering est désactivé — auquel cas `normalize_wav`
    se comporte exactement comme avant (loudnorm seul, non-régression).
    """
    if not cfg.get("enabled", True):
        return []

    filters: list[str] = []

    highpass = cfg.get("highpass_hz")
    if highpass:
        filters.append(f"highpass=f={int(highpass)}")

    for band in cfg.get("eq") or []:
        freq = band.get("f")
        gain = band.get("g", 0)
        width = band.get("w", 1)
        if freq and gain:
            filters.append(
                f"equalizer=f={int(freq)}:t=q:w={float(width)}:g={float(gain)}"
            )

    if cfg.get("deesser"):
        if deesser_available:
            filters.append("deesser")
        else:
            logger.warning(
                "Filtre ffmpeg 'deesser' indisponible — étape de-esser ignorée"
            )

    comp = cfg.get("compressor") or {}
    if comp:
        filters.append(
            "acompressor="
            f"threshold={comp.get('threshold_db', -18)}dB:"
            f"ratio={comp.get('ratio', 3)}:"
            f"attack={comp.get('attack_ms', 15)}:"
            f"release={comp.get('release_ms', 120)}:"
            f"makeup={comp.get('makeup_db', 2)}"
        )

    return filters


async def ffmpeg_has_filter(name: str) -> bool:
    """True si la build ffmpeg locale expose le filtre `name`. Résultat mis en cache."""
    if name in _filter_cache:
        return _filter_cache[name]

    available = False
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-filters",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode(errors="ignore").splitlines():
            tokens = line.split()
            if len(tokens) >= 2 and tokens[1] == name:
                available = True
                break
    except Exception as exc:  # ffmpeg absent / build minimale
        logger.warning(
            "Probe ffmpeg filters échouée (%s) — suppose '%s' indisponible", exc, name
        )
        available = False

    _filter_cache[name] = available
    return available


async def build_audio_filter(mastering: dict[str, Any] | None = None) -> str:
    """Construit la chaîne `-af` complète : mastering + loudnorm broadcast final.

    `mastering=None` → config globale. Le loudnorm reste toujours en dernier.
    """
    cfg = mastering if mastering is not None else load_audio_mastering_config()
    chain: list[str] = []
    if cfg.get("enabled", True):
        deesser_ok = await ffmpeg_has_filter("deesser") if cfg.get("deesser") else False
        chain = build_mastering_chain(cfg, deesser_available=deesser_ok)
    return ",".join([*chain, "loudnorm=I=-16:TP=-1.5:LRA=11"])
