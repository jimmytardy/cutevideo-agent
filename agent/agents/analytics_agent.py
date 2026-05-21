from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.channel_config import resolve_channel_config
from agent.core.database import Analytics, AsyncSessionFactory
from agent.core.learning_context import (
    load_channel_context,
    merge_llm_context_update,
    scheduled_analysis_hour,
)
from agent.scheduler.engagement import PublicationJob, current_utc_hour, list_published_publications
from agent.skills.publisher import youtube_analytics

logger = logging.getLogger(__name__)

ANALYTICS_SYSTEM = """Tu es un expert en performance de vidéos éducatives YouTube et TikTok.
Tu analyses les métriques, identifies ce qui fonctionne ou non, et mets à jour un contexte
d'apprentissage pour améliorer les prochaines productions.
Tu peux INVALIDER des insights précédents si les nouvelles données les contredisent.
Tu retournes UNIQUEMENT du JSON valide."""

ANALYTICS_PROMPT_TEMPLATE = """Analyse les performances de cette vidéo publiée.

PLATEFORME : {platform}
TITRE : {title}
CHAÎNE : {channel_name} ({theme_category})

MÉTRIQUES ACTUELLES :
{metrics_json}

HISTORIQUE DES SNAPSHOTS (du plus ancien au plus récent) :
{history_json}

CONTEXTE D'APPRENTISSAGE ACTUEL DE LA CHAÎNE :
{current_context}

Retourne UNIQUEMENT ce JSON :
{{
  "summary": "Résumé synthétique pour guider les prochaines vidéos (max 400 mots)",
  "performance_verdict": "success | mixed | underperforming",
  "new_insights": [
    {{
      "text": "Insight actionnable pour les prochaines vidéos",
      "source": "analytics",
      "confidence": 0.85,
      "evidence": "Donnée ou tendance qui supporte l'insight"
    }}
  ],
  "invalidate_insight_ids": ["id-insight-devenu-faux"],
  "update_insights": [
    {{"id": "id-existant", "confidence": 0.2, "active": false}}
  ]
}}

Règles :
- Invalide les insights dont la confiance tombe sous 0.35 face aux nouvelles métriques
- Sois factuel : ne suppose pas de causes sans indicateur dans les métriques
- Focus : hook, rétention, engagement, format court vs long"""


class AnalyticsAgent(BaseAgent):
    """Agent 10 — Analytics : métriques quotidiennes et contexte d'apprentissage chaîne."""

    name = "analytics_agent"

    async def run_scheduled(self, force_all: bool = False) -> dict[str, int]:
        hour = current_utc_hour()
        jobs = await list_published_publications()
        processed = 0
        errors = 0

        for job in jobs:
            if not force_all and scheduled_analysis_hour(job.publication.id) != hour:
                continue
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

        logger.info("Analytics planifié : %d traités, %d erreurs (heure UTC %d)", processed, errors, hour)
        return {"processed": processed, "errors": errors}

    async def run_for_publication(self, publication_id: uuid.UUID) -> dict[str, Any]:
        jobs = await list_published_publications()
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
            history = await self._load_analytics_history(pub.id)
            current_ctx = await load_channel_context(channel.id)

            prompt = ANALYTICS_PROMPT_TEMPLATE.format(
                platform=pub.platform or "unknown",
                title=pub.title or "",
                channel_name=channel.name,
                theme_category=channel.theme_category,
                metrics_json=json.dumps(metrics, ensure_ascii=False, indent=2),
                history_json=json.dumps(history, ensure_ascii=False, indent=2),
                current_context=current_ctx.format_for_prompt(),
            )
            raw = await self._call_claude(prompt, system=ANALYTICS_SYSTEM, max_tokens=4096)
            llm_data = self._parse_json(raw)

            await self._save_analytics_snapshot(pub.id, metrics)
            snapshot = await merge_llm_context_update(channel.id, llm_data)

            output = {
                "publication_id": str(pub.id),
                "verdict": llm_data.get("performance_verdict"),
                "context_version": snapshot.version,
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
            "note": "Métriques TikTok détaillées non disponibles via API — utiliser vues/likes si présents en DB",
        }

    async def _load_analytics_history(self, publication_id: uuid.UUID) -> list[dict[str, Any]]:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Analytics)
                .where(Analytics.publication_id == publication_id)
                .order_by(Analytics.fetched_at.asc())
                .limit(14)
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

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
