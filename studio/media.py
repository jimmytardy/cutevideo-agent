"""Recherche, téléchargement et inspection des médias pour Claude Studio.

Couche fine au-dessus de `agent/skills/media_sources/*` : les candidats sont
mis en cache dans `media/candidates.json` (ids courts `c1`, `c2`…) pour que
Claude puisse les prévisualiser puis télécharger ceux qu'il retient, et les
droits de chaque fichier téléchargé sont tenus dans `media/credits.json`.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import importlib
import inspect
import json
import logging
import math
import os
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp

from agent.core.concurrency import bounded_gather
from agent.skills.media.rights_check import filter_publishable
from agent.skills.video.ffmpeg_runtime import filter_thread_args, measure_loudness, run_ffmpeg, thread_args
from studio.assets import FONT_FILE, IMAGE_EXTENSIONS, SHEET_COLS, TILE_H, TILE_W, ai_models, max_ai_images
from studio.contracts import (
    AI_CACHE_DIR,
    AI_DIR,
    AI_LOCK_FILE,
    AI_USAGE_FILE,
    ContractError,
    cache_key,
    read_json,
    write_json,
)
from studio.user_keys import FAL_KEY, GCP_CREDENTIALS_JSON, GCP_LOCATION, user_key

if TYPE_CHECKING:
    from agent.core.api_keys import GcpCredentials

logger = logging.getLogger(__name__)

SOURCES = (
    "pexels", "pixabay", "unsplash", "coverr", "wikimedia",
    "nasa", "europeana", "internet_archive", "gallica",
)
DEFAULT_SOURCES = ("pexels", "pixabay", "unsplash", "coverr", "wikimedia")
MAX_RESULTS_PER_SOURCE = 6
DOWNLOAD_TIMEOUT_S = 90





# ── registres JSON du run dir ─────────────────────────────────────────────


def _candidates_path(run_dir: Path) -> Path:
    return run_dir / "media" / "candidates.json"


def _credits_path(run_dir: Path) -> Path:
    return run_dir / "media" / "credits.json"


def record_credit(run_dir: Path, rel_path: str, entry: dict[str, Any]) -> None:
    credits = read_json(_credits_path(run_dir), {})
    credits[rel_path] = entry
    write_json(_credits_path(run_dir), credits)


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

    cache = read_json(_candidates_path(run_dir), {})
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
    write_json(_candidates_path(run_dir), cache)
    return out


def _candidate(run_dir: Path, cid: str) -> dict[str, Any]:
    cache = read_json(_candidates_path(run_dir), {})
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


def verify_image(path: Path) -> None:
    """Vérifie qu'une image se décode entièrement (pas seulement son en-tête).

    Un fichier tronqué, ou une page HTML renvoyée en 200 sous un nom .jpg, passe `ffprobe` mais fait boucler
    `ffmpeg -loop 1` sans fin au rendu : on le refuse ici avec un message pour Claude.
    """
    from PIL import Image

    try:
        with Image.open(path) as img:
            img.load()
    except Image.DecompressionBombError as exc:
        raise ContractError(
            f"image trop grande pour être traitée : {path.name} ({str(exc)[:120]}) — choisis un autre candidat"
        ) from exc
    except Exception as exc:  # Pillow lève OSError, ValueError, SyntaxError, struct.error… selon le format
        raise ContractError(
            f"image corrompue ou illisible : {path.name} ({str(exc)[:120]}) — re-télécharge ou choisis un autre candidat"
        ) from exc


async def verify_media(path: Path) -> dict[str, Any]:
    """Média lisible : image entièrement décodée, vidéo/audio sondés par ffprobe. Renvoie le `probe_media()`."""
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        verify_image(path)
    try:
        return await probe_media(path)
    except RuntimeError as exc:
        raise ContractError(
            f"média corrompu ou illisible : {path.name} ({str(exc)[:120]}) — re-télécharge ou choisis un autre candidat"
        ) from exc


async def _verified_cache_file(cached: Path, fetch) -> None:
    """Télécharge (si absent) puis vérifie un fichier du cache ; un fichier illisible est évincé avant de lever,
    sinon il serait réutilisé à chaque nouvelle tentative."""
    if not cached.exists():
        await fetch()
    try:
        await verify_media(cached)
    except ContractError:
        cached.unlink(missing_ok=True)
        raise


async def _cached_download(run_dir: Path, cid: str) -> Path:
    item = _candidate(run_dir, cid)
    cached = run_dir / "media" / ".cache" / f"{cid}{_extension_for(item)}"

    async def fetch() -> None:
        await _fetch(str(item["url"]), cached)
        if item.get("source") == "coverr" and item.get("coverr_video_id"):
            from agent.skills.media_sources.coverr import record_download

            await record_download(str(item["coverr_video_id"]))

    await _verified_cache_file(cached, fetch)
    return cached


async def _preview_source(run_dir: Path, cid: str) -> Path:
    """Vignette fournie par la source si dispo (évite de télécharger la vidéo entière)."""
    item = _candidate(run_dir, cid)
    thumb_url = item.get("thumbnail_url") or item.get("thumbnail")
    if item.get("asset_type") == "video" and thumb_url:
        thumb = run_dir / "media" / ".cache" / f"{cid}_thumb.jpg"
        await _verified_cache_file(thumb, lambda: _fetch(str(thumb_url), thumb))
        return thumb
    return await _cached_download(run_dir, cid)


async def download_candidate(run_dir: Path, cid: str, name: str) -> dict[str, Any]:
    item = _candidate(run_dir, cid)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or cid
    cached = await _cached_download(run_dir, cid)
    dest = run_dir / "media" / f"{safe}{cached.suffix}"
    shutil.copy2(cached, dest)
    rel = str(dest.relative_to(run_dir))
    info = await probe_media(dest)  # le cache a déjà été vérifié ; crédit enregistré seulement pour un média lisible
    record_credit(run_dir, rel, _credit_entry(item))
    return {"path": rel, **info, "license": item.get("license"), "author": item.get("author")}


def _user_gcp_credentials() -> GcpCredentials | None:
    """Compte de service GCP du propriétaire (Imagen 3), posé par le launcher."""
    from agent.core.api_keys import GcpCredentials
    from agent.core.config import settings
    from agent.core.vertex import vertex_project_id

    credentials_json = user_key(GCP_CREDENTIALS_JSON)
    if not credentials_json:
        return None
    try:
        project_id = vertex_project_id(credentials_json)
    except RuntimeError:
        return None
    location = user_key(GCP_LOCATION) or settings.gcp_location
    return GcpCredentials(project_id=project_id, location=location, credentials_json=credentials_json)


def _billed_generations(run_dir: Path) -> int:
    """Nombre d'appels payants au fournisseur d'images depuis le début de la création.

    Un registre illisible lève plutôt que de repartir de zéro : remettre le compteur à zéro rouvrirait
    le plafond, et c'est l'argent du propriétaire de la chaîne.
    """
    path = run_dir / AI_USAGE_FILE
    try:
        return max(0, int(read_json(path, {}).get("billed", 0)))
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise RuntimeError(
            f"registre de dépense des images IA illisible ({exc}) : n'y touche pas et ne réessaie pas, "
            "illustre ce plan avec une banque d'images ou une animation du kit"
        ) from exc


def _write_billed(run_dir: Path, count: int) -> None:
    """Écrit le registre de façon atomique : un processus tué ne laisse jamais de compteur tronqué."""
    path = run_dir / AI_USAGE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps({"billed": count}), encoding="utf-8")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def _ai_budget_lock(run_dir: Path) -> Iterator[None]:
    """Sérialise « vérifier le plafond → générer → compter » entre les sous-processus `studio.tools`.

    Chaque commande est un processus distinct et Claude peut en lancer plusieurs dans le même tour :
    sans ce verrou, deux appels lancés à `plafond - 1` le franchiraient tous les deux et seraient tous
    les deux facturés. Le verrou est relâché par le noyau si le processus meurt.

    `flock` est bloquant, ce qui est sans conséquence ici : le seul appelant est `cmd_ai_image`, et
    chaque commande `studio.tools` a son propre processus. Un second appel **dans le même processus**
    s'interbloquerait — à revoir si un jour un outil enchaîne plusieurs générations.
    """
    lock_path = run_dir / AI_LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _cached_ai_image(run_dir: Path, key: str) -> tuple[Path, dict[str, Any]] | None:
    """Image déjà générée pour cette clé, ou `None` s'il faut repasser par le fournisseur.

    Toute entrée douteuse — méta illisible, fichier absent ou image tronquée — est effacée et traitée
    comme une absence : un cache abîmé coûte une génération, jamais une création ratée.
    """
    meta_path = run_dir / AI_CACHE_DIR / f"{key}.json"
    path: Path | None = None
    try:
        meta = read_json(meta_path, None)
        if not isinstance(meta, dict):
            return None
        path = meta_path.with_suffix(meta["suffix"])
        verify_image(path)
        return path, dict(meta["credit"])
    except (ContractError, OSError, ValueError, TypeError, KeyError):
        # Méta d'un format antérieur, tronquée, ou image abîmée : on régénère plutôt que de planter.
        if path is not None:
            path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        return None


def _store_ai_image(run_dir: Path, key: str, src: Path, credit: dict[str, Any], meta: dict[str, Any]) -> None:
    """Copie l'image dans le cache, méta écrite en dernier : une copie interrompue n'est jamais reprise."""
    cache_dir = run_dir / AI_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix or ".png"
    tmp = cache_dir / f".{key}.{os.getpid()}.tmp{suffix}"
    try:
        shutil.copy2(src, tmp)
        tmp.replace(cache_dir / f"{key}{suffix}")
        write_json(cache_dir / f"{key}.json", {**meta, "suffix": suffix, "credit": credit})
    except OSError as exc:
        # L'image est payée et valide : la rendre prime sur la mise en cache, qui n'est qu'une économie.
        tmp.unlink(missing_ok=True)
        logger.warning("Image IA non mise en cache (%s) : %s", key, exc)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def generate_ai_image(
    run_dir: Path, prompt: str, name: str, aspect: str = "9:16", model: str | None = None
) -> dict[str, Any]:
    allowed = ai_models()
    if not allowed:
        raise RuntimeError(
            "images IA indisponibles (désactivées par la chaîne ou aucune clé fal / GCP) : "
            "utilise une banque d'images ou une animation du kit (anim/lib/studio.js)"
        )
    model = model or allowed[0]
    if model not in allowed:
        raise RuntimeError(f"modèle {model} non autorisé pour cette chaîne : choisis parmi {', '.join(allowed)}")
    key = cache_key({"prompt": prompt, "model": model, "aspect": aspect})
    # Le cache est consulté hors du verrou : rien n'est facturé, donc le plafond n'a pas à être consulté
    # et relancer un prompt déjà généré reste possible même une fois les générations épuisées.
    cached = _cached_ai_image(run_dir, key)
    reused = cached is not None
    if cached is None:
        with _ai_budget_lock(run_dir):
            # Un appel concurrent a pu produire l'image pendant qu'on attendait le verrou.
            cached = _cached_ai_image(run_dir, key)
            reused = cached is not None
            if cached is None:
                cached = await _generate_ai_image(
                    run_dir, key, prompt=prompt, name=name, aspect=aspect, model=model, allowed=allowed
                )
    src, credit = cached
    dest = run_dir / "media" / f"{name}{src.suffix or '.png'}"
    shutil.copy2(src, dest)
    rel = str(dest.relative_to(run_dir))
    record_credit(run_dir, rel, credit)
    return {"path": rel, **(await probe_media(dest)), "reused": reused}


async def _generate_ai_image(
    run_dir: Path, key: str, *, prompt: str, name: str, aspect: str, model: str, allowed: list[str]
) -> tuple[Path, dict[str, Any]]:
    """Appel payant au fournisseur, sous le verrou de budget. Rend l'image et son crédit.

    La génération est **comptée d'avance** et seulement décomptée si le fournisseur confirme n'avoir
    rien produit. C'est le sens de marche sûr : le groupe de processus est tué sans ménagement
    (redéploiement du worker, surveillance d'inactivité) et un kill pendant les deux minutes de l'appel
    laisserait sinon une image payée hors du compteur, que la reprise relancerait.
    """
    from agent.skills.media_sources.ai.base import ImageBilledButLost
    from agent.skills.media_sources.ai_image import generate_image

    billed = _billed_generations(run_dir)
    if billed >= max_ai_images():
        raise RuntimeError(
            f"plafond d'images IA atteint ({billed}/{max_ai_images()} générations facturées) : "
            "utilise les banques d'images, une animation du kit (anim/lib/studio.js), ou reprends "
            "un prompt déjà généré"
        )
    _write_billed(run_dir, billed + 1)
    try:
        result = await generate_image(
            prompt,
            run_dir / AI_DIR / name,
            plan=model,
            aspect_ratio=aspect,
            # Clés du propriétaire de la chaîne, posées par le launcher.
            fal_api_key=user_key(FAL_KEY),
            gcp_credentials=_user_gcp_credentials() if model.startswith("imagen") else None,
        )
    except ImageBilledButLost as exc:
        # Le fournisseur avait accepté la requête : elle est payée, la réservation reste acquise.
        raise RuntimeError(
            f"génération {model} facturée mais image non récupérée ({exc}) : réessaie une fois, "
            "sinon illustre ce plan avec une animation du kit ou une banque d'images"
        ) from exc
    except Exception:
        # Panne que le fournisseur n'a pas su classer (jeton GCP expiré, bug) : il aurait levé
        # `ImageBilledButLost` si l'image avait été produite, donc rien n'a été payé. Sans ce
        # remboursement, quatre pannes de ce genre épuiseraient le plafond sans un centime dépensé.
        # `BaseException` est volontairement exclu : un processus tué garde sa réservation.
        _write_billed(run_dir, billed)
        raise
    if not result:
        # Refusée avant d'atteindre le modèle (clé invalide, prompt filtré) : rien n'est dû, on rend
        # la réservation.
        _write_billed(run_dir, billed)
        others = [m for m in allowed if m != model]
        hint = f"réessaie avec --model {others[0]} ou " if others else ""
        raise RuntimeError(
            f"génération {model} échouée (clé refusée ou prompt bloqué) : {hint}illustre ce plan avec "
            "une animation du kit (anim/lib/studio.js) ou une banque d'images"
        )
    src = Path(result["local_generated"])
    credit = {
        "source": "ai_image",
        "license": "ai_generated",
        "author": result.get("provider_plan"),
        "attribution": result.get("attribution") or "Image générée par IA",
        "source_url": None,
        "requires_attribution": False,
    }
    try:
        verify_image(src)
    except ContractError:
        # Déjà comptée. Le crédit sous media/.ai garde la trace de la dépense et du modèle en cause ;
        # il n'entre jamais dans l'attribution publiée, qui ne retient que les médias cités par la
        # timeline (`_used_credits()` dans studio/render.py).
        record_credit(run_dir, str(src.relative_to(run_dir)), {**credit, "unusable": True})
        raise
    _store_ai_image(run_dir, key, src, credit, {"prompt": prompt, "model": model, "aspect": aspect})
    return src, credit


async def fetch_music(run_dir: Path, mood: str) -> dict[str, Any]:
    from agent.skills.audio.music_fetcher import fetch_music_for_mood

    out_dir = run_dir / "media" / "music"
    # Piste plus longue que la voix (+ marge pour le retrait des silences) : évite une boucle audible.
    voice = read_json(run_dir / "voice.json", {})
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
    return (await measure_loudness(path))[0]


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


async def sheet_from_images(images: list[tuple[Path, str]], out: Path) -> None:
    """Planche contact d'images déjà rendues (aperçu d'animation), avec les repères de zones."""
    work = out.parent / ".work"
    work.mkdir(parents=True, exist_ok=True)
    tiles: list[Path] = []
    for i, (image, label) in enumerate(images):
        tile = work / f"t{i:03d}.png"
        await _tile_from(image, tile, label, guides=True)
        tiles.append(tile)
    await _build_sheet(tiles, out)


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
