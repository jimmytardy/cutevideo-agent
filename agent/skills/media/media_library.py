from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update

from agent.core.config import load_agent_config
from agent.core.database import AsyncSessionFactory, MediaAsset
from agent.core.media_validation import MediaValidationBrief
from agent.core.visual_beats import VisualBeat

logger = logging.getLogger(__name__)

LIBRARY_SELECTED = "selected"
LIBRARY_POOL = "pool"
LIBRARY_REJECTED = "rejected"


@dataclass(frozen=True)
class MediaLibraryConfig:
    enabled: bool = True
    pool_min_score: int = 70
    reuse_min_score: int = 80
    max_pool_size_per_project: int = 100
    scope: str = "project"


def load_media_library_config(channel_overrides: dict[str, Any] | None = None) -> MediaLibraryConfig:
    global_cfg = load_agent_config().get("media_library", {})
    channel_cfg: dict[str, Any] = {}
    if channel_overrides:
        channel_cfg = channel_overrides.get("media_library", {})
        if not isinstance(channel_cfg, dict):
            channel_cfg = {}
    merged = {**global_cfg, **channel_cfg}
    return MediaLibraryConfig(
        enabled=bool(merged.get("enabled", True)),
        pool_min_score=int(merged.get("pool_min_score", 70)),
        reuse_min_score=int(merged.get("reuse_min_score", 80)),
        max_pool_size_per_project=int(merged.get("max_pool_size_per_project", 100)),
        scope=str(merged.get("scope", "project")),
    )


async def archive_current_selection(project_id: uuid.UUID) -> int:
    """Passe tous les assets selected en pool (conservation fichiers)."""
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            update(MediaAsset)
            .where(
                MediaAsset.project_id == project_id,
                MediaAsset.library_status == LIBRARY_SELECTED,
            )
            .values(selected=False, library_status=LIBRARY_POOL)
        )
        await session.commit()
        count = result.rowcount or 0
        if count:
            logger.info("Bibliothèque : %d asset(s) archivé(s) en pool pour %s", count, project_id)
        return count


async def query_pool(
    project_id: uuid.UUID,
    *,
    segment_order: int | None = None,
) -> list[MediaAsset]:
    async with AsyncSessionFactory() as session:
        stmt = (
            select(MediaAsset)
            .where(
                MediaAsset.project_id == project_id,
                MediaAsset.library_status == LIBRARY_POOL,
            )
            .order_by(MediaAsset.relevance_score.desc().nullslast(), MediaAsset.created_at.desc())
        )
        if segment_order is not None:
            stmt = stmt.where(MediaAsset.segment_order == segment_order)
        result = await session.execute(stmt)
        return list(result.scalars().all())


def _asset_to_candidate(asset: MediaAsset) -> dict[str, Any]:
    return {
        "source": asset.source,
        "url": asset.source_url or asset.local_path,
        "local_generated": asset.local_path,
        "license": asset.license,
        "attribution": asset.attribution,
        "author": asset.author,
        "requires_attribution": asset.requires_attribution,
        "title": asset.generation_prompt or asset.relevance_reason or "",
        "asset_type": asset.asset_type or "image",
        "_relevance_score": asset.relevance_score,
        "_relevance_reason": asset.relevance_reason,
        "_library_asset_id": str(asset.id),
        "_visual_type": asset.visual_type,
    }


async def try_reuse_for_beat(
    *,
    beat: VisualBeat,
    segment: dict[str, Any],
    pool_assets: list[MediaAsset],
    validation_brief: MediaValidationBrief,
    video_subject: str,
    channel_category: str,
    min_score: int,
    api_key: str,
    output_dir: Any,
    segment_order: int,
) -> tuple[MediaAsset | None, int]:
    """Retourne (asset réutilisé, score) ou (None, 0)."""
    if not pool_assets:
        return None, 0

    from agent.skills.media.rights_check import is_publishable

    publishable_assets = [a for a in pool_assets if is_publishable(a)[0]]
    if not publishable_assets:
        return None, 0

    from agent.core.visual_beats import beat_narration_excerpt
    from agent.skills.media_sources.relevance_scorer import score_media_candidates

    candidates = [_asset_to_candidate(a) for a in publishable_assets]
    scored = await score_media_candidates(
        candidates,
        video_subject=video_subject,
        channel_category=channel_category,
        segment_title=segment.get("title", ""),
        segment_narration=beat_narration_excerpt(beat),
        api_key=api_key,
        cache_dir=output_dir / "scoring",
        validation_brief=validation_brief,
        segment_order=segment_order,
        beat=beat,
    )
    if not scored:
        return None, 0

    best = max(scored, key=lambda s: s.score)
    if best.score < min_score:
        return None, best.score

    asset_id = best.candidate.get("_library_asset_id")
    if not asset_id:
        return None, 0

    async with AsyncSessionFactory() as session:
        asset = await session.get(MediaAsset, uuid.UUID(asset_id))
        if asset is None:
            return None, 0
        asset.library_status = LIBRARY_SELECTED
        asset.selected = True
        asset.beat_index = beat.order
        asset.segment_order = segment_order
        asset.relevance_score = best.score
        asset.relevance_reason = best.reason
        asset.visual_type = beat.visual_type
        await session.commit()
        await session.refresh(asset)
        logger.info(
            "Beat %d segment %d : réutilisation pool asset %s (score=%d)",
            beat.order,
            segment_order,
            asset.id,
            best.score,
        )
        return asset, best.score


def promote_to_pool(
    asset: MediaAsset,
    *,
    pool_min_score: int,
) -> None:
    score = asset.relevance_score or 0
    if score < pool_min_score:
        asset.library_status = LIBRARY_REJECTED
        asset.selected = False
        return
    asset.library_status = LIBRARY_POOL
    asset.selected = False


async def trim_pool(project_id: uuid.UUID, max_size: int) -> None:
    pool = await query_pool(project_id)
    if len(pool) <= max_size:
        return
    to_reject = pool[max_size:]
    async with AsyncSessionFactory() as session:
        for asset in to_reject:
            row = await session.get(MediaAsset, asset.id)
            if row:
                row.library_status = LIBRARY_REJECTED
                row.selected = False
        await session.commit()


async def count_pool(project_id: uuid.UUID) -> int:
    assets = await query_pool(project_id)
    return len(assets)


def pool_summary_for_prompt(pool_count: int) -> str:
    if pool_count <= 0:
        return "Bibliothèque média : aucune image en pool pour ce projet."
    return (
        f"Bibliothèque média : {pool_count} image(s) réutilisables en pool. "
        "Ne regénère que les beats explicitement concernés par la correction."
    )
