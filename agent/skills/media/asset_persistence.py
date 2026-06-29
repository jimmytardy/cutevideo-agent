from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.core.concurrency import bounded_gather
from agent.core.database import AsyncSessionFactory, MediaAsset
from agent.core.media_asset_resolve import clip_metadata_for_media_item, find_existing_local_path
from agent.skills.media.asset_perception import load_perception_config, perceive_asset, perception_to_dict
from agent.skills.media.rights_check import media_asset_rights_fields

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext
    from agent.core.visual_beats import VisualBeat
    from agent.skills.media.run_session import MediaRunSession

logger = logging.getLogger(__name__)


def rights_fields(item: dict) -> dict[str, Any]:
    fields = media_asset_rights_fields(item)
    return {
        **fields,
        "attribution": fields.get("attribution") or item.get("attribution"),
    }


async def download_asset(item: dict, output_dir: Path) -> Path | None:
    if item.get("local_generated"):
        return Path(item["local_generated"])

    import aiohttp

    url = item.get("url")
    if not url or url.startswith("/"):
        return Path(url) if url and Path(url).exists() else None
    raw_name = url.split("/")[-1].split("?")[0] or ""
    if raw_name and "." in raw_name:
        filename = raw_name
    elif item.get("asset_type") == "video":
        filename = "clip.mp4"
    else:
        filename = "image.jpg"
    dest = output_dir / filename
    if dest.exists():
        return dest
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    dest.write_bytes(await resp.read())
                    if item.get("source") == "coverr":
                        video_id = item.get("coverr_video_id")
                        if video_id:
                            from agent.skills.media_sources.coverr import record_download

                            await record_download(str(video_id))
                    return dest
    except Exception as e:
        logger.warning("Téléchargement échoué %s : %s", url, e)
    return None


async def analyze_video_asset(
    session: MediaRunSession,
    ctx: PipelineContext,
    path: Path,
    item: dict,
    beat: VisualBeat,
    segment_order: int,
) -> tuple[float | None, dict | None]:
    from agent.skills.media.clip_source_analyzer import (
        analyze_clip_source,
        clip_metadata_to_dict,
    )
    from agent.skills.video.ffmpeg_utils import _probe_clip_duration

    try:
        duration = float(item.get("duration_s") or await _probe_clip_duration(path))
    except Exception:
        duration = None
    if not duration:
        return None, None
    if not session.gemini_api_key:
        return duration, None
    context = f"{beat.phrase_anchor} — {beat.prompt}"
    meta = await analyze_clip_source(
        path,
        context=context,
        duration_s=duration,
        api_key=session.gemini_api_key,
    )
    if meta and (meta.useful_duration_s or 0) < 3.0:
        logger.warning("Clip vidéo rejeté (durée utile < 3s) : %s", path)
        return duration, clip_metadata_to_dict(meta)
    return duration, clip_metadata_to_dict(meta) if meta else None


async def apply_perception(
    session: MediaRunSession,
    ctx: PipelineContext,
    *,
    path: Path | None,
    asset_type: str,
    context: str = "",
    duration_s: float | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    cfg = load_perception_config()
    if not cfg.get("enabled", True):
        return None, None
    if not session.gemini_api_key:
        return None, None
    max_assets = int(cfg.get("max_assets_per_video", 20))
    if session.perception_calls_used >= max_assets:
        return None, None

    resolved = path
    if resolved is None or not resolved.is_file():
        return None, None

    meta, file_hash, cache_hit = await perceive_asset(
        resolved,
        asset_type=asset_type,
        theme=ctx.theme,
        api_key=session.gemini_api_key,
        context=context,
        duration_s=duration_s,
    )
    if meta is not None and not cache_hit:
        session.perception_calls_used += 1
    return perception_to_dict(meta), file_hash


async def apply_perception_batch(
    session: MediaRunSession,
    ctx: PipelineContext,
    pending: list[tuple[MediaAsset, Path | None, str, float | None]],
) -> None:
    async def _one(
        entry: tuple[MediaAsset, Path | None, str, float | None],
    ) -> None:
        asset, local_path, context, duration_s = entry
        path = local_path
        if path is None and asset.local_path:
            path = find_existing_local_path(asset.local_path)
        perception, file_hash = await apply_perception(
            session,
            ctx,
            path=path,
            asset_type=str(asset.asset_type or "image"),
            context=context,
            duration_s=duration_s,
        )
        asset.perception = perception
        asset.file_hash = file_hash

    await bounded_gather(*[_one(entry) for entry in pending], return_exceptions=True)


async def persist_beat_asset(
    session: MediaRunSession,
    ctx: PipelineContext,
    *,
    item: dict,
    segment_order: int,
    beat: VisualBeat,
    output_dir: Path,
    generation_prompt: str,
    media_iteration: int,
) -> MediaAsset:
    local_path = await download_asset(item, output_dir)
    duration_s = item.get("duration_s")
    clip_metadata = clip_metadata_for_media_item(item)
    path_obj = Path(local_path) if local_path else None
    if path_obj and path_obj.exists() and item.get("asset_type") == "video":
        duration_s, video_meta = await analyze_video_asset(
            session, ctx, path_obj, item, beat, segment_order,
        )
        if video_meta:
            clip_metadata = {**(clip_metadata or {}), **video_meta}
    perception, file_hash = await apply_perception(
        session,
        ctx,
        path=path_obj,
        asset_type=str(item.get("asset_type", "image")),
        context=f"{beat.phrase_anchor} — {beat.prompt}",
        duration_s=float(duration_s) if duration_s else None,
    )
    async with AsyncSessionFactory() as session_db:
        rights = rights_fields(item)
        asset = MediaAsset(
            project_id=ctx.project_id,
            segment_order=segment_order,
            beat_index=beat.order,
            source=item.get("source"),
            source_url=rights["source_url"],
            local_path=str(local_path) if local_path else item.get("local_generated"),
            license=rights["license"],
            attribution=rights["attribution"] or item.get("attribution"),
            author=rights["author"],
            requires_attribution=rights["requires_attribution"],
            asset_type=item.get("asset_type", "image"),
            selected=True,
            relevance_score=item.get("_relevance_score"),
            relevance_reason=item.get("_relevance_reason"),
            library_status="selected",
            generation_prompt=generation_prompt,
            visual_type=beat.visual_type,
            iteration=media_iteration,
            duration_s=float(duration_s) if duration_s else None,
            clip_metadata=clip_metadata,
            perception=perception,
            file_hash=file_hash,
        )
        session_db.add(asset)
        await session_db.commit()
        await session_db.refresh(asset)
        return asset


async def persist_pool_candidate(
    session: MediaRunSession,
    ctx: PipelineContext,
    item: dict,
    segment_order: int,
    beat: VisualBeat,
    output_dir: Path,
    pool_min_score: int,
    media_iteration: int,
) -> None:
    from agent.skills.media.media_library import promote_to_pool

    local_path = await download_asset(item, output_dir)
    rights = rights_fields(item)
    async with AsyncSessionFactory() as session_db:
        asset = MediaAsset(
            project_id=ctx.project_id,
            segment_order=segment_order,
            beat_index=beat.order,
            source=item.get("source"),
            source_url=rights["source_url"],
            local_path=str(local_path) if local_path else item.get("local_generated"),
            license=rights["license"],
            attribution=rights["attribution"] or item.get("attribution"),
            author=rights["author"],
            requires_attribution=rights["requires_attribution"],
            asset_type=item.get("asset_type", "image"),
            selected=False,
            relevance_score=item.get("_relevance_score"),
            relevance_reason=item.get("_relevance_reason"),
            library_status="pool",
            generation_prompt=item.get("_generation_prompt") or beat.prompt,
            visual_type=beat.visual_type,
            iteration=media_iteration,
            clip_metadata=clip_metadata_for_media_item(item),
        )
        await promote_to_pool(asset, pool_min_score=pool_min_score)
        session_db.add(asset)
        await session_db.commit()
