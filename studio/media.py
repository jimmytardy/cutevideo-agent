"""Recherche, téléchargement et inspection des médias pour Claude Studio.

Couche fine au-dessus de `agent/skills/media_sources/*` : les candidats sont
mis en cache dans `media/candidates.json` (ids courts `c1`, `c2`…) pour que
Claude puisse les prévisualiser puis télécharger ceux qu'il retient, et les
droits de chaque fichier téléchargé sont tenus dans `media/credits.json`.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import math
import os
import re
import shutil
from pathlib import Path
from typing import Any

import aiohttp

from agent.core.concurrency import bounded_gather
from agent.skills.media.rights_check import filter_publishable
from agent.skills.video.ffmpeg_runtime import filter_thread_args, run_ffmpeg, thread_args
from studio.textfx import FONT_FILE

logger = logging.getLogger(__name__)

SOURCES = (
    "pexels", "pixabay", "unsplash", "coverr", "wikimedia",
    "nasa", "europeana", "internet_archive", "gallica",
)
DEFAULT_SOURCES = ("pexels", "pixabay", "unsplash", "coverr", "wikimedia")
MAX_RESULTS_PER_SOURCE = 6
DOWNLOAD_TIMEOUT_S = 90
TILE_W, TILE_H = 270, 480
SHEET_COLS = 4

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp"}


def max_ai_images() -> int:
    try:
        return max(0, int(os.getenv("STUDIO_MAX_AI_IMAGES", "4")))
    except ValueError:
        return 4


# ── registres JSON du run dir ─────────────────────────────────────────────


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _candidates_path(run_dir: Path) -> Path:
    return run_dir / "media" / "candidates.json"


def _credits_path(run_dir: Path) -> Path:
    return run_dir / "media" / "credits.json"


def record_credit(run_dir: Path, rel_path: str, entry: dict[str, Any]) -> None:
    credits = _read_json(_credits_path(run_dir), {})
    credits[rel_path] = entry
    _write_json(_credits_path(run_dir), credits)


def _credit_entry(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": item.get("source"),
        "license": item.get("license"),
        "author": item.get("author"),
        "attribution": item.get("attribution"),
        "source_url": item.get("source_url") or item.get("url"),
        "requires_attribution": bool(item.get("requires_attribution")),
    }


# ── recherche ─────────────────────────────────────────────────────────────


async def _search_source(
    source: str, keywords: list[str], media_type: str, orientation: str
) -> list[dict[str, Any]]:
    module = importlib.import_module(f"agent.skills.media_sources.{source}")
    kwargs: dict[str, Any] = {"media_type": media_type}
    if "orientation" in inspect.signature(module.search).parameters:
        kwargs["orientation"] = orientation
    try:
        results = await module.search(keywords, "", **kwargs)
    except Exception as exc:  # une source en panne ne doit pas bloquer les autres
        logger.warning("Recherche %s échouée : %s", source, exc)
        return []
    return list(results or [])[:MAX_RESULTS_PER_SOURCE]


async def search_media(
    run_dir: Path,
    query: str,
    *,
    media_type: str = "image",
    sources: list[str] | None = None,
    orientation: str = "portrait",
) -> list[dict[str, Any]]:
    chosen = [s for s in (sources or DEFAULT_SOURCES) if s in SOURCES]
    unknown = set(sources or []) - set(SOURCES)
    if unknown:
        raise ValueError(f"sources inconnues : {', '.join(sorted(unknown))} (dispo : {', '.join(SOURCES)})")
    keywords = query.split()
    batches = await bounded_gather(
        *(_search_source(s, keywords, media_type, orientation) for s in chosen)
    )
    raw = [item for batch in batches for item in batch]
    accepted, _rejected = filter_publishable(raw)

    cache = _read_json(_candidates_path(run_dir), {})
    out: list[dict[str, Any]] = []
    for item in accepted:
        if not item.get("url"):
            continue
        cid = f"c{len(cache) + 1}"
        cache[cid] = {**item, "query": query}
        entry = {
            "id": cid,
            "source": item.get("source"),
            "type": item.get("asset_type") or media_type,
            "title": (item.get("title") or "")[:120],
            "license": item.get("license"),
            "author": item.get("author"),
            "duration_s": item.get("duration") or item.get("duration_s"),
            "width": item.get("width"),
            "height": item.get("height"),
        }
        out.append({k: v for k, v in entry.items() if v not in (None, "")})
    _write_json(_candidates_path(run_dir), cache)
    return out


def _candidate(run_dir: Path, cid: str) -> dict[str, Any]:
    cache = _read_json(_candidates_path(run_dir), {})
    if cid not in cache:
        raise ValueError(f"candidat inconnu : {cid} (lance d'abord search-media)")
    return cache[cid]


# ── téléchargement ────────────────────────────────────────────────────────


def _extension_for(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "")
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix and len(suffix) <= 5:
        return suffix
    return ".mp4" if item.get("asset_type") == "video" else ".jpg"


async def _fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT_S)
    headers = {"User-Agent": "cutevideo-studio/1.0 (+https://github.com)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} pour {url}")
            tmp = dest.with_suffix(dest.suffix + ".part")
            with tmp.open("wb") as fh:
                async for chunk in resp.content.iter_chunked(1 << 16):
                    fh.write(chunk)
            tmp.replace(dest)


async def _cached_download(run_dir: Path, cid: str) -> Path:
    item = _candidate(run_dir, cid)
    cached = run_dir / "media" / ".cache" / f"{cid}{_extension_for(item)}"
    if not cached.exists():
        await _fetch(str(item["url"]), cached)
        if item.get("source") == "coverr" and item.get("coverr_video_id"):
            from agent.skills.media_sources.coverr import record_download

            await record_download(str(item["coverr_video_id"]))
    return cached


async def _preview_source(run_dir: Path, cid: str) -> Path:
    """Vignette fournie par la source si dispo (évite de télécharger la vidéo entière)."""
    item = _candidate(run_dir, cid)
    thumb_url = item.get("thumbnail_url") or item.get("thumbnail")
    if item.get("asset_type") == "video" and thumb_url:
        thumb = run_dir / "media" / ".cache" / f"{cid}_thumb.jpg"
        if not thumb.exists():
            await _fetch(str(thumb_url), thumb)
        return thumb
    return await _cached_download(run_dir, cid)


async def download_candidate(run_dir: Path, cid: str, name: str) -> dict[str, Any]:
    item = _candidate(run_dir, cid)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or cid
    cached = await _cached_download(run_dir, cid)
    dest = run_dir / "media" / f"{safe}{cached.suffix}"
    shutil.copy2(cached, dest)
    rel = str(dest.relative_to(run_dir))
    record_credit(run_dir, rel, _credit_entry(item))
    info = await probe_media(dest)
    return {"path": rel, **info, "license": item.get("license"), "author": item.get("author")}


async def generate_ai_image(run_dir: Path, prompt: str, name: str, aspect: str = "9:16") -> dict[str, Any]:
    from agent.core.channel_config import AiFallbackConfig
    from agent.core.config import settings
    from agent.skills.media_sources.ai_image import generate_image

    credits = _read_json(_credits_path(run_dir), {})
    used = sum(1 for c in credits.values() if c.get("source") == "ai_image")
    if used >= max_ai_images():
        raise RuntimeError(
            f"quota d'images IA atteint ({used}/{max_ai_images()}) : utilise les banques d'images"
        )
    out_dir = run_dir / "media" / ".ai" / name
    result = await generate_image(
        prompt,
        out_dir,
        ai_cfg=AiFallbackConfig(),
        aspect_ratio=aspect,
        plan_override="flux_2_dev",
        use_prompt_as_is=True,
        visual_type="custom",
        # generate_image ne lit pas la clé globale (user_resolved_keys) : on la passe explicitement.
        fal_api_key=settings.fal_key or None,
    )
    if not result or not result.get("local_generated"):
        raise RuntimeError(
            "génération IA indisponible (clé FAL absente ou refusée) : illustre ce plan avec une animation "
            "du kit (anim/lib/studio.js) ou une banque d'images"
        )
    src = Path(result["local_generated"])
    dest = run_dir / "media" / f"{name}{src.suffix or '.png'}"
    shutil.copy2(src, dest)
    rel = str(dest.relative_to(run_dir))
    record_credit(run_dir, rel, {
        "source": "ai_image",
        "license": "ai_generated",
        "author": result.get("provider_plan"),
        "attribution": result.get("attribution") or "Image générée par IA",
        "source_url": None,
        "requires_attribution": False,
    })
    return {"path": rel, **(await probe_media(dest))}


async def fetch_music(run_dir: Path, mood: str) -> dict[str, Any]:
    from agent.skills.audio.music_fetcher import fetch_music_for_mood

    out_dir = run_dir / "media" / "music"
    # Piste plus longue que la voix (+ marge pour le retrait des silences) : évite une boucle audible.
    voice = _read_json(run_dir / "voice.json", {})
    min_duration = int(float(voice.get("duration_s") or 0) + 6)
    path = await fetch_music_for_mood(mood, output_dir=out_dir, min_duration_s=min_duration)
    if not path:
        raise RuntimeError(f"aucune musique trouvée pour le mood {mood!r}")
    rel = str(path.relative_to(run_dir))
    source = "freesound" if "freesound" in path.name else "internet_archive"
    record_credit(run_dir, rel, {
        "source": source,
        "license": "open",
        "author": None,
        "attribution": f"Musique : {source} ({path.stem})",
        "source_url": None,
        "requires_attribution": source == "freesound",
    })
    return {"path": rel, **(await probe_media(path))}


# ── inspection ────────────────────────────────────────────────────────────


async def _run_capture(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def probe_media(path: Path) -> dict[str, Any]:
    code, out, err = await _run_capture([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of", "json", str(path),
    ])
    if code != 0:
        raise RuntimeError(f"ffprobe a échoué sur {path.name} : {err.strip()[:200]}")
    data = json.loads(out or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    is_image = path.suffix.lower() in IMAGE_EXTENSIONS
    duration = float(data.get("format", {}).get("duration") or 0.0)
    return {
        "kind": "image" if is_image else ("video" if video else "audio"),
        "duration_s": 0.0 if is_image else round(duration, 3),
        "width": video.get("width"),
        "height": video.get("height"),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


async def loudness(path: Path) -> float | None:
    """Loudness intégrée (LUFS) via le filtre ebur128."""
    _code, _out, err = await _run_capture([
        "ffmpeg", "-nostats", "-i", str(path), "-map", "0:a:0", "-af", "ebur128", "-f", "null", "-",
    ])
    matches = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    return float(matches[-1]) if matches else None


# Repères des zones (planches d'animation) : bande des sous-titres et colonne d'icônes TikTok, à l'échelle tuile.
_GUIDES = (
    f"drawbox=x=0:y={int(1220 * TILE_H / 1920)}:w=iw:h={int(140 * TILE_H / 1920)}:color=red@0.25:t=fill,"
    f"drawbox=x={int(960 * TILE_W / 1080)}:y=0:w=2:h=ih:color=red@0.6:t=fill,"
)


async def _tile_from(src: Path, out: Path, label: str, *, seek: float | None = None, guides: bool = False) -> None:
    font = f":fontfile={FONT_FILE}" if Path(FONT_FILE).exists() else ""
    label_file = out.with_suffix(".txt")
    label_file.write_text(label, encoding="utf-8")
    seek_args = ["-ss", f"{seek:.2f}"] if seek is not None else []
    await run_ffmpeg([
        "ffmpeg", "-y", *filter_thread_args(), *seek_args, "-i", str(src),
        "-vf", (
            f"scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=increase,crop={TILE_W}:{TILE_H},"
            f"{_GUIDES if guides else ''}"
            f"drawtext=textfile='{label_file}'{font}:fontsize=26:fontcolor=yellow:"
            "box=1:boxcolor=black@0.7:boxborderw=6:x=8:y=8"
        ),
        "-frames:v", "1", *thread_args(), str(out),
    ], error_prefix=f"Vignette {label}")
    label_file.unlink(missing_ok=True)


async def _build_sheet(tiles: list[Path], out: Path) -> None:
    cols = min(SHEET_COLS, len(tiles))
    rows = math.ceil(len(tiles) / cols)
    work = tiles[0].parent
    ordered = [work / f"tile_{i:03d}.png" for i in range(rows * cols)]
    for i, dest in enumerate(ordered):
        if i < len(tiles):
            if tiles[i] != dest:
                tiles[i].replace(dest)
        else:
            await run_ffmpeg([
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={TILE_W}x{TILE_H}",
                "-frames:v", "1", *thread_args(), str(dest),
            ], error_prefix="Vignette vide")
    out.parent.mkdir(parents=True, exist_ok=True)
    await run_ffmpeg([
        "ffmpeg", "-y", *filter_thread_args(), "-i", str(work / "tile_%03d.png"),
        "-vf", f"tile={cols}x{rows}:padding=4:color=white",
        "-frames:v", "1", *thread_args(), str(out),
    ], error_prefix="Planche contact")
    shutil.rmtree(work, ignore_errors=True)


async def preview_candidates(run_dir: Path, ids: list[str]) -> dict[str, Any]:
    """Planche contact des candidats (vignettes 9:16 étiquetées par id)."""
    sheets_dir = run_dir / "media" / "previews"
    work = sheets_dir / f".work_{os.getpid()}"
    work.mkdir(parents=True, exist_ok=True)
    tiles: list[Path] = []
    failed: dict[str, str] = {}
    for cid in ids:
        try:
            src = await _preview_source(run_dir, cid)
            tile = work / f"{cid}.png"
            is_video = src.suffix.lower() not in IMAGE_EXTENSIONS
            await _tile_from(src, tile, cid, seek=1.0 if is_video else None)
            tiles.append(tile)
        except Exception as exc:
            failed[cid] = str(exc)[:160]
    if not tiles:
        shutil.rmtree(work, ignore_errors=True)
        return {"sheet": None, "failed": failed}
    index = len(list(sheets_dir.glob("sheet_*.png"))) + 1
    sheet = sheets_dir / f"sheet_{index:02d}.png"
    await _build_sheet(tiles, sheet)
    return {"sheet": str(sheet.relative_to(run_dir)), "failed": failed}


async def extract_frames(
    run_dir: Path, video: Path, every_s: float, out_dir: Path, *, guides: bool = False
) -> dict[str, Any]:
    """Frames régulières d'une vidéo + planche contact (pour la critique)."""
    info = await probe_media(video)
    duration = info["duration_s"]
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / ".work"
    work.mkdir(exist_ok=True)
    stamps = [round(t, 2) for t in _frange(0.3, max(duration - 0.1, 0.4), every_s)]
    frames: list[str] = []
    tiles: list[Path] = []
    for i, t in enumerate(stamps):
        frame = out_dir / f"frame_{i:03d}_{t:05.1f}s.jpg"
        await run_ffmpeg([
            "ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
            *thread_args(), "-q:v", "3", str(frame),
        ], error_prefix="Extraction frame")
        frames.append(str(frame.relative_to(run_dir)))
        tile = work / f"t{i:03d}.png"
        await _tile_from(frame, tile, f"{t:.1f}s", guides=guides)
        tiles.append(tile)
    sheet = out_dir / "sheet.png"
    await _build_sheet(tiles, sheet)
    return {
        "duration_s": duration,
        "frames": frames,
        "sheet": str(sheet.relative_to(run_dir)),
        "loudness_lufs": await loudness(video) if info["has_audio"] else None,
    }


def _frange(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    t = start
    while t < stop:
        values.append(t)
        t += step
    return values or [start]
