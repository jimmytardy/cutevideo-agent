from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select

from agent.core.base_agent import BaseAgent
from agent.core.channel_config import resolve_channel_config
from agent.core.database import (
    AsyncSessionFactory,
    Channel,
    Project,
    Publication,
    Scenario,
    Video,
)
from agent.core.learning_context import load_channel_context
from agent.scheduler.distribution_slots import (
    DailyQuotas,
    filter_occupied_slots,
    generate_candidate_slots,
    is_short_video_type,
    parse_platform_slots,
    paris_day_bounds,
    pick_best_slot,
)
from agent.scheduler.editorial_calendar import publication_target_day
from agent.skills.publisher.executor import (
    channel_supports_platform,
    platform_for_video_type,
    publish_scheduled,
)

logger = logging.getLogger(__name__)

SLOT_PICK_SYSTEM = """Tu choisis le meilleur créneau de publication pour une vidéo éducative.
Tu retournes UNIQUEMENT du JSON : {"slot_index": 0} où slot_index est l'index du créneau recommandé (0 = le plus tôt)."""

SLOT_PICK_PROMPT = """Chaîne : {channel_name} ({theme_category})
Plateforme : {platform}
Type vidéo : {video_type}
Titre : {title}

Contexte apprentissage :
{learning_context}

Créneaux candidats (UTC ISO, du plus proche au plus lointain) :
{slots_json}

Retourne {"slot_index": N} avec N entre 0 et {max_index}."""


class DistributionAgent(BaseAgent):
    """Agent distribution — planification et publication optimisée YT / TikTok / Instagram."""

    name = "distribution_agent"

    async def run(self, input_data: None = None) -> dict[str, Any]:  # type: ignore[override]
        return await self.run_scheduled()

    async def run_scheduled(self) -> dict[str, Any]:
        try:
            planned = await self._plan_all_channels()
            executed = await self._execute_due()
            output = {"planned": planned, "executed": executed}
            logger.info("Distribution terminée : %s", output)
            return output
        except Exception as e:
            logger.error("Distribution échouée : %s", e)
            raise

    async def _plan_all_channels(self) -> int:
        planned = 0
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Channel).where(Channel.is_active == True)  # noqa: E712
            )
            channels = list(result.scalars().all())

        for channel in channels:
            cfg = resolve_channel_config(channel)
            if not cfg.auto_publish:
                continue
            n = await self._plan_channel(channel, cfg)
            planned += n
        return planned

    async def _plan_channel(self, channel: Channel, cfg: Any) -> int:
        raw_slots = parse_platform_slots(cfg.platform_slots)
        enabled = set(cfg.enabled_platforms or [])
        platform_slots = {k: v for k, v in raw_slots.items() if not enabled or k in enabled}
        if not platform_slots:
            logger.warning("Aucun platform_slots pour %s — planification ignorée", channel.slug)
            return 0

        quotas = DailyQuotas(long=cfg.daily_quotas.long, short=cfg.daily_quotas.short)
        target_day = publication_target_day()
        long_scheduled_today, short_scheduled_today = await self._count_scheduled_for_day(
            channel.id, target_day
        )
        long_published_today, short_published_today = await self._count_published_for_day(
            channel.id, target_day
        )

        long_remaining = max(0, quotas.long - long_scheduled_today - long_published_today)
        short_remaining = max(0, quotas.short - short_scheduled_today - short_published_today)

        if long_remaining == 0 and short_remaining == 0:
            return 0

        candidates = await self._videos_pending_publish(channel.id, target_day)
        long_videos = [v for v in candidates if not is_short_video_type(v.video_type)]
        short_videos = [v for v in candidates if is_short_video_type(v.video_type)]

        planned = 0
        metadata_cache: dict[uuid.UUID, tuple[str, str, list[str]]] = {}

        for video in long_videos:
            if long_remaining <= 0:
                break
            if await self._schedule_video(
                channel, cfg, video, platform_slots, metadata_cache, target_day
            ):
                long_remaining -= 1
                planned += 1

        for video in short_videos:
            if short_remaining <= 0:
                break
            if await self._schedule_video(
                channel, cfg, video, platform_slots, metadata_cache, target_day
            ):
                short_remaining -= 1
                planned += 1

        return planned

    async def _schedule_video(
        self,
        channel: Channel,
        cfg: Any,
        video: Video,
        platform_slots: dict,
        metadata_cache: dict[uuid.UUID, tuple[str, str, list[str]]],
        target_publish_day: date,
    ) -> bool:
        platform = platform_for_video_type(video.video_type)
        if not platform or not channel_supports_platform(channel, platform):
            return False
        if cfg.enabled_platforms and platform not in cfg.enabled_platforms:
            return False

        if video.file_purged_at:
            return False
        if not video.storage_key and not (video.local_path and Path(video.local_path).exists()):
            return False

        if await self._has_publication_for_video(video.id, platform):
            return False

        occupied = await self._occupied_slots(channel.id, platform)
        candidates = generate_candidate_slots(
            platform,
            platform_slots,
            cfg.timezone,
            after_utc=datetime.now(timezone.utc),
            only_day=target_publish_day,
        )
        candidates = filter_occupied_slots(candidates, occupied)
        if not candidates:
            logger.info(
                "Pas de créneau libre pour %s / %s le %s (vidéo %s)",
                channel.slug,
                platform,
                target_publish_day.isoformat(),
                video.id,
            )
            return False

        title, description, tags = await self._metadata_for_video(
            video, channel, cfg, metadata_cache
        )
        slot_index = await self._pick_slot_index(
            channel, cfg, video, platform, title, candidates[:3]
        )
        scheduled_at = pick_best_slot(candidates, slot_index)
        if not scheduled_at:
            return False

        reason = {
            "platform": platform,
            "video_type": video.video_type,
            "slot_index": slot_index,
            "target_publish_date": target_publish_day.isoformat(),
            "candidates_utc": [c.isoformat() for c in candidates[:3]],
            "timezone": cfg.timezone,
        }

        async with AsyncSessionFactory() as session:
            pub = Publication(
                video_id=video.id,
                channel_id=channel.id,
                platform=platform,
                title=title,
                description=description,
                hashtags=tags,
                scheduled_at=scheduled_at,
                scheduling_reason=reason,
                status="scheduled",
            )
            session.add(pub)
            await session.commit()

        logger.info(
            "Planifié %s/%s vidéo %s à %s",
            channel.slug,
            platform,
            video.id,
            scheduled_at.isoformat(),
        )
        return True

    async def _pick_slot_index(
        self,
        channel: Channel,
        cfg: Any,
        video: Video,
        platform: str,
        title: str,
        candidates: list[datetime],
    ) -> int | None:
        if len(candidates) <= 1:
            return 0
        try:
            learning = await load_channel_context(channel.id)
            prompt = SLOT_PICK_PROMPT.format(
                channel_name=channel.name,
                theme_category=channel.theme_category,
                platform=platform,
                video_type=video.video_type or "long",
                title=title,
                learning_context=learning.format_for_prompt(),
                slots_json=json.dumps([c.isoformat() for c in candidates], ensure_ascii=False),
                max_index=len(candidates) - 1,
            )
            raw = await self._call_claude(prompt, system=SLOT_PICK_SYSTEM, max_tokens=256)
            data = self._parse_json(raw)
            return int(data.get("slot_index", 0))
        except Exception as e:
            logger.debug("Choix créneau LLM ignoré (%s) : %s", channel.slug, e)
            return 0

    async def _execute_due(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        published = 0
        failed = 0

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Publication, Video, Channel)
                .join(Video, Publication.video_id == Video.id)
                .join(Channel, Publication.channel_id == Channel.id)
                .where(
                    Publication.status == "scheduled",
                    Publication.scheduled_at <= now,
                )
                .order_by(Publication.scheduled_at.asc())
            )
            rows = list(result.all())

        for pub, video, channel in rows:
            cfg = resolve_channel_config(channel)
            outcome = await publish_scheduled(pub, channel, cfg, video)
            if outcome and outcome.status == "published":
                published += 1
            else:
                failed += 1

        logger.info("Distribution execute : %d publiées, %d échouées", published, failed)
        return {"published": published, "failed": failed}

    async def _videos_pending_publish(
        self,
        channel_id: uuid.UUID,
        target_publish_day: date,
    ) -> list[Video]:
        target_iso = target_publish_day.isoformat()
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Video, Project)
                .join(Project, Video.project_id == Project.id)
                .where(
                    Project.channel_id == channel_id,
                    Project.status == "approved",
                    Video.file_purged_at.is_(None),
                )
                .order_by(
                    Video.video_type.asc(),
                    Video.created_at.asc(),
                )
            )
            rows = list(result.all())

        pending: list[Video] = []
        async with AsyncSessionFactory() as session:
            existing = await session.execute(
                select(Publication.video_id, Publication.platform).where(
                    Publication.channel_id == channel_id,
                    Publication.status.in_(("scheduled", "publishing", "published")),
                )
            )
            taken = {(row[0], row[1]) for row in existing.all()}

        for video, project in rows:
            cfg = project.config or {}
            pub_date = cfg.get("target_publish_date")
            if pub_date and pub_date != target_iso:
                continue
            platform = platform_for_video_type(video.video_type)
            if platform and (video.id, platform) not in taken:
                pending.append(video)
        return pending

    async def _has_publication_for_video(self, video_id: uuid.UUID, platform: str) -> bool:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(func.count())
                .select_from(Publication)
                .where(
                    Publication.video_id == video_id,
                    Publication.platform == platform,
                    Publication.status.in_(("scheduled", "publishing", "published")),
                )
            )
            return int(result.scalar_one()) > 0

    async def _occupied_slots(self, channel_id: uuid.UUID, platform: str) -> set[datetime]:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Publication.scheduled_at, Publication.published_at).where(
                    Publication.channel_id == channel_id,
                    Publication.platform == platform,
                    or_(
                        Publication.status == "scheduled",
                        Publication.status == "published",
                    ),
                )
            )
            occupied: set[datetime] = set()
            for sched, pub_at in result.all():
                dt = sched or pub_at
                if dt:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    occupied.add(dt)
            return occupied

    async def _count_published_for_day(
        self,
        channel_id: uuid.UUID,
        day: date,
    ) -> tuple[int, int]:
        from agent.scheduler.distribution_slots import to_utc

        start, end = paris_day_bounds(day)
        return await self._count_by_type(
            channel_id, to_utc(start), to_utc(end), published_only=True
        )

    async def _count_scheduled_for_day(
        self,
        channel_id: uuid.UUID,
        day: date,
    ) -> tuple[int, int]:
        from agent.scheduler.distribution_slots import to_utc

        start, end = paris_day_bounds(day)
        return await self._count_by_type(channel_id, to_utc(start), to_utc(end), scheduled_only=True)

    async def _count_by_type(
        self,
        channel_id: uuid.UUID,
        start_utc: datetime,
        end_utc: datetime,
        published_only: bool = False,
        scheduled_only: bool = False,
    ) -> tuple[int, int]:
        if published_only:
            statuses = ("published",)
            time_col = Publication.published_at
        elif scheduled_only:
            statuses = ("scheduled",)
            time_col = Publication.scheduled_at
        else:
            statuses = ("scheduled", "published")
            time_col = Publication.scheduled_at

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Video.video_type, func.count())
                .join(Publication, Publication.video_id == Video.id)
                .where(
                    Publication.channel_id == channel_id,
                    Publication.status.in_(statuses),
                    time_col.isnot(None),
                    time_col >= start_utc,
                    time_col < end_utc,
                )
                .group_by(Video.video_type)
            )
            long_count = 0
            short_count = 0
            for vtype, cnt in result.all():
                if is_short_video_type(vtype):
                    short_count += int(cnt)
                else:
                    long_count += int(cnt)
            return long_count, short_count

    async def _metadata_for_video(
        self,
        video: Video,
        channel: Channel,
        cfg: Any,
        cache: dict[uuid.UUID, tuple[str, str, list[str]]],
    ) -> tuple[str, str, list[str]]:
        if video.project_id in cache:
            return cache[video.project_id]

        title = "Vidéo éducative"
        description = ""
        tags = list(cfg.default_tags)

        async with AsyncSessionFactory() as session:
            project = await session.get(Project, video.project_id)
            if project:
                description = project.theme
            scenario_result = await session.execute(
                select(Scenario)
                .where(Scenario.project_id == video.project_id)
                .order_by(Scenario.created_at.desc())
                .limit(1)
            )
            scenario = scenario_result.scalar_one_or_none()
            if scenario and scenario.segments:
                first = scenario.segments[0] if isinstance(scenario.segments, list) else {}
                if isinstance(first, dict):
                    title = str(first.get("title", title))

        cache[video.project_id] = (title, description, tags)
        return title, description, tags

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
