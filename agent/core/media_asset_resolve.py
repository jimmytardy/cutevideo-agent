from __future__ import annotations

import uuid
from pathlib import Path

from agent.core.database import MediaAsset
from agent.core.storage import download_storage_key, get_presigned_url, is_s3_storage_enabled

_APP_ROOT = Path("/app")


def local_path_candidates(local_path: str | None) -> list[Path]:
    if not local_path:
        return []
    raw = local_path.strip()
    if not raw:
        return []

    primary = Path(raw)
    candidates = [primary]
    if primary.is_absolute():
        return candidates

    candidates.append(_APP_ROOT / raw)
    candidates.append(_APP_ROOT / raw.lstrip("./"))
    candidates.append(Path(raw).resolve())
    return candidates


def find_existing_local_path(local_path: str | None) -> Path | None:
    for candidate in local_path_candidates(local_path):
        if candidate.is_file():
            return candidate
    return None


def storage_key_for_asset(
    asset: MediaAsset,
    project_config: dict | None,
) -> str | None:
    meta = asset.clip_metadata if isinstance(asset.clip_metadata, dict) else {}
    key = meta.get("temp_s3_key")
    if isinstance(key, str) and key:
        return key

    if asset.source != "ai_image" or asset.segment_order is None:
        return None

    keys = temp_s3_keys_for_segment(project_config, int(asset.segment_order))
    if len(keys) == 1:
        return keys[0]
    return None


def temp_s3_keys_for_segment(project_config: dict | None, segment_order: int) -> list[str]:
    keys = list((project_config or {}).get("temp_ai_image_keys") or [])
    needle = f"/ai/{segment_order}/"
    return [k for k in keys if isinstance(k, str) and needle in k]


async def resolve_media_asset_stream_target(
    asset: MediaAsset,
    project_config: dict | None,
) -> tuple[str, str] | None:
    """Retourne ('file', path) ou ('redirect', url) si le média est disponible."""
    local = find_existing_local_path(asset.local_path)
    if local is not None:
        return ("file", str(local))

    storage_key = storage_key_for_asset(asset, project_config)
    if storage_key and is_s3_storage_enabled():
        suffix = _suffix_for_asset(asset)
        cached = Path(f"./tmp/media_stream_cache/{asset.id}{suffix}")
        if cached.is_file():
            return ("file", str(cached.resolve()))
        try:
            await download_storage_key(storage_key, cached)
            return ("file", str(cached.resolve()))
        except Exception:
            url = await get_presigned_url(storage_key)
            return ("redirect", url)

    if asset.source_url and asset.source_url.startswith("http"):
        suffix = _suffix_for_asset(asset)
        cached = Path(f"./tmp/media_stream_cache/{asset.id}{suffix}")
        if cached.is_file():
            return ("file", str(cached.resolve()))
        downloaded = await _download_http_asset(asset.source_url, cached)
        if downloaded is not None:
            return ("file", str(downloaded.resolve()))
        return ("redirect", asset.source_url)

    return None


def _suffix_for_asset(asset: MediaAsset) -> str:
    for raw in (asset.local_path, asset.source_url):
        if not raw:
            continue
        suffix = Path(str(raw).split("?")[0]).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm"}:
            return suffix
    if getattr(asset, "asset_type", None) == "video":
        return ".mp4"
    return ".jpg"


async def _download_http_asset(url: str, dest: Path) -> Path | None:
    import aiohttp

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    return None
                dest.write_bytes(await resp.read())
                return dest
    except Exception:
        return None


async def materialize_media_asset_local(
    asset: MediaAsset,
    project_config: dict | None,
    *,
    suffix: str = ".jpg",
) -> Path | None:
    local = find_existing_local_path(asset.local_path)
    if local is not None:
        return local

    storage_key = storage_key_for_asset(asset, project_config)
    if not storage_key or not is_s3_storage_enabled():
        return None

    dest = Path(f"./tmp/media_stream/{asset.id}{suffix}")
    return await download_storage_key(storage_key, dest)


def clip_metadata_for_media_item(item: dict) -> dict | None:
    meta = dict(item.get("clip_metadata") or {})
    temp_key = item.get("_temp_s3_key")
    if temp_key:
        meta["temp_s3_key"] = str(temp_key)
    return meta or None
