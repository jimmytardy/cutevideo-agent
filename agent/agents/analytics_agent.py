from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.channel_config import resolve_channel_config
from agent.core.database import Analytics, AsyncSessionFactory
from agent.core.learning_context import merge_llm_context_update
from agent.core.llm_config import is_engagement_run_day, max_publications_per_engagement_run
from agent.scheduler.engagement import (
    PublicationJob,
    analytics_history_limit,
    list_published_publications,
)
from agent.skills.analytics.metrics_rules import analyze_metrics_with_pandas
from agent.skills.publisher import youtube_analytics

logger = logging.getLogger(__name__)


class AnalyticsAgent(BaseAgent):
    """Agent 10 — Analytics : métriques 2×/semaine, analyse pandas sans LLM."""

    name = "analytics_agent"

    async def run_scheduled(self, force_all: bool = False) -> dict[str, int]:
        if not force_all and not is_engagement_run_day(date.today()):
            logger.info("Analytics ignoré — hors jour planifié (engagement_run_weekdays)")
            return {"processed": 0, "errors": 0, "skipped": "not_scheduled_day"}

        jobs = await list_published_publications(force_all=force_all)
        cap = max_publications_per_engagement_run()
        jobs = jobs[:cap]

        processed = 0
        errors = 0

        for job in jobs:
            cfg = resolve_channel_config(job.channel)
            if not cfg.analytics_enabled:
                continue
            try:
                await self._analyze_publication(job)
                processed += 1
            except Exception as e:
                errors += 1
                logger.error(
                    "Analytics échoué publication %s : %s",
                    job.publication.id,
                    e,
                )

        logger.info("Analytics planifié : %d traités, %d erreurs", processed, errors)
        return {"processed": processed, "errors": errors}

    async def run_for_publication(self, publication_id: uuid.UUID) -> dict[str, Any]:
        if not is_engagement_run_day(date.today()):
            raise ValueError(
                "Analytics manuel autorisé uniquement les jours engagement_run_weekdays"
            )
        jobs = await list_published_publications(force_all=True)
        job = next((j for j in jobs if j.publication.id == publication_id), None)
        if not job:
            raise ValueError(f"Publication {publication_id} introuvable ou non publiée")
        return await self._analyze_publication(job)

    async def _analyze_publication(self, job: PublicationJob) -> dict[str, Any]:
        pub = job.publication
        channel = job.channel
        run = await self.start_run(
            job.project_id,
            {"publication_id": str(pub.id), "platform": pub.platform},
        )
        try:
            metrics = await self._fetch_metrics(pub, channel)
            history = await self._load_analytics_history(pub.id, job.video_type)
            rule_payload = analyze_metrics_with_pandas(
                metrics,
                history,
                title=pub.title or "",
                platform=pub.platform or "",
            )

            await self._save_analytics_snapshot(pub.id, metrics)
            snapshot = await merge_llm_context_update(channel.id, rule_payload)

            output = {
                "publication_id": str(pub.id),
                "verdict": rule_payload.get("performance_verdict"),
                "context_version": snapshot.version,
                "method": "pandas_rules",
            }
            await self.end_run(run, output)
            return output
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _fetch_metrics(
        self,
        pub: Any,
        channel: Any,
    ) -> dict[str, Any]:
        platform = (pub.platform or "").lower()
        video_id = pub.platform_video_id
        if not video_id:
            return {"error": "missing_platform_video_id"}

        if platform == "youtube":
            return await youtube_analytics.fetch_video_metrics(
                video_id,
                refresh_token=channel.youtube_refresh_token,
            )
        return {
            "platform": platform,
            "video_id": video_id,
            "views": 0,
            "likes": 0,
            "comments": 0,
            "note": "Métriques TikTok détaillées non disponibles via API",
        }

    async def _load_analytics_history(
        self,
        publication_id: uuid.UUID,
        video_type: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = analytics_history_limit(video_type)
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Analytics)
                .where(Analytics.publication_id == publication_id)
                .order_by(Analytics.fetched_at.asc())
                .limit(limit)
            )
            rows = list(result.scalars().all())
        return [
            {
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                "views": r.views,
                "likes": r.likes,
                "comments": r.comments,
                "retention_percent": r.retention_percent,
                "raw_metrics": r.raw_metrics,
            }
            for r in rows
        ]

    async def _save_analytics_snapshot(
        self,
        publication_id: uuid.UUID,
        metrics: dict[str, Any],
    ) -> None:
        async with AsyncSessionFactory() as session:
            row = Analytics(
                publication_id=publication_id,
                views=int(metrics.get("views", 0) or 0),
                likes=int(metrics.get("likes", 0) or 0),
                comments=int(metrics.get("comments", 0) or 0),
                raw_metrics=metrics,
            )
            session.add(row)
            await session.commit()
