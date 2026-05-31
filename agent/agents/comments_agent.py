from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.channel_config import resolve_channel_config
from agent.core.database import AsyncSessionFactory, PlatformComment
from agent.core.learning_context import merge_llm_context_update
from agent.core.llm_config import is_engagement_run_day, max_publications_per_engagement_run
from agent.scheduler.engagement import PublicationJob, list_published_publications
from agent.skills.comments.heuristics import (
    classify_comments,
    results_to_analysis_payload,
    rule_based_comment_insights,
)
from agent.skills.publisher import tiktok_comments, youtube_comments
from agent.skills.publisher.composio_client import tiktok_is_connected

logger = logging.getLogger(__name__)

COMMENTS_LLM_SYSTEM = """Tu es community manager pour des chaînes éducatives YouTube et TikTok en français.
Tu analyses UNIQUEMENT les commentaires marqués needs_llm.
Tu retournes UNIQUEMENT du JSON valide."""

COMMENTS_LLM_PROMPT = """Commentaires nécessitant une analyse LLM :

{comments_json}

Retourne UNIQUEMENT ce JSON :
{{
  "comments_analysis": [
    {{
      "platform_comment_id": "id",
      "needs_reply": true,
      "reply_text": "Réponse courte (max 280 car.) ou null",
      "status": "replied | ignored | spam",
      "is_constructive": true,
      "constructive_note": "string ou null"
    }}
  ],
  "summary": "Synthèse courte (max 150 mots)",
  "new_insights": [
    {{"text": "...", "source": "comments", "confidence": 0.75, "evidence": "..."}}
  ],
  "invalidate_insight_ids": [],
  "update_insights": []
}}"""


class CommentsAgent(BaseAgent):
    """Agent 11 — Commentaires : heuristiques 2×/semaine, Sonnet pour cas ambigus."""

    name = "comments_agent"

    async def run_scheduled(self, force_all: bool = False) -> dict[str, int]:
        if not force_all and not is_engagement_run_day(date.today()):
            logger.info("Comments ignoré — hors jour planifié (engagement_run_weekdays)")
            return {"processed": 0, "errors": 0, "skipped": "not_scheduled_day"}

        jobs = await list_published_publications(force_all=force_all)
        cap = max_publications_per_engagement_run()
        jobs = jobs[:cap]

        processed = 0
        errors = 0

        for job in jobs:
            cfg = resolve_channel_config(job.channel)
            if not cfg.comments_enabled:
                continue
            try:
                await self._process_publication(job)
                processed += 1
            except Exception as e:
                errors += 1
                logger.error(
                    "Comments échoué publication %s : %s",
                    job.publication.id,
                    e,
                )

        logger.info("Comments planifié : %d traités, %d erreurs", processed, errors)
        return {"processed": processed, "errors": errors}

    async def run_for_publication(self, publication_id: uuid.UUID) -> dict[str, Any]:
        if not is_engagement_run_day(date.today()):
            raise ValueError(
                "Comments manuel autorisé uniquement les jours engagement_run_weekdays"
            )
        jobs = await list_published_publications(force_all=True)
        job = next((j for j in jobs if j.publication.id == publication_id), None)
        if not job:
            raise ValueError(f"Publication {publication_id} introuvable ou non publiée")
        return await self._process_publication(job)

    async def _process_publication(self, job: PublicationJob) -> dict[str, Any]:
        pub = job.publication
        channel = job.channel
        cfg = resolve_channel_config(channel)
        run = await self.start_run(
            job.project_id,
            {"publication_id": str(pub.id), "platform": pub.platform},
        )
        try:
            fetched = await self._fetch_and_store_comments(pub, channel, cfg.max_comments_fetched)
            new_comments = [c for c in fetched if c.status == "new"]
            if not new_comments:
                await self.end_run(run, {"replies": 0, "new_comments": 0})
                return {"replies": 0, "new_comments": 0}

            comments_payload = [
                {
                    "platform_comment_id": c.platform_comment_id,
                    "author": c.author_name,
                    "text": c.text,
                    "status": c.status,
                }
                for c in new_comments
            ]

            heuristic_results = classify_comments(comments_payload)
            analysis_payload = results_to_analysis_payload(heuristic_results)

            replies_sent = 0
            if cfg.auto_reply_comments:
                replies_sent = await self._apply_replies(
                    pub, channel, analysis_payload, cfg.max_replies_per_run
                )

            llm_needing = [r for r in heuristic_results if r.needs_llm]
            merge_payload = rule_based_comment_insights(heuristic_results)

            if llm_needing:
                llm_comments = [
                    c
                    for c in comments_payload
                    if any(
                        r.platform_comment_id == c["platform_comment_id"] and r.needs_llm
                        for r in llm_needing
                    )
                ]
                prompt = COMMENTS_LLM_PROMPT.format(
                    comments_json=json.dumps(llm_comments, ensure_ascii=False, indent=2),
                )
                raw = await self._call_claude_for_channel(
                    channel.id,
                    prompt,
                    system=COMMENTS_LLM_SYSTEM,
                )
                llm_data = self._parse_json(raw)
                llm_analyses = llm_data.get("comments_analysis", [])
                by_id = {a["platform_comment_id"]: a for a in llm_analyses if a.get("platform_comment_id")}
                for item in analysis_payload:
                    lid = item["platform_comment_id"]
                    if lid in by_id:
                        item.update(by_id[lid])
                if cfg.auto_reply_comments:
                    extra = await self._apply_replies(
                        pub, channel, llm_analyses, cfg.max_replies_per_run - replies_sent
                    )
                    replies_sent += extra
                if llm_data.get("new_insights") or llm_data.get("summary"):
                    merge_payload["summary"] = str(llm_data.get("summary") or merge_payload["summary"])
                    merge_payload["new_insights"] = (
                        merge_payload.get("new_insights", []) + llm_data.get("new_insights", [])
                    )[:2]

            if merge_payload.get("new_insights") or merge_payload.get("summary"):
                await merge_llm_context_update(channel.id, merge_payload)

            await self._mark_comments_processed(analysis_payload)

            output = {
                "replies": replies_sent,
                "new_comments": len(new_comments),
                "llm_comments": len(llm_needing),
                "method": "heuristics+sonnet" if llm_needing else "heuristics",
            }
            await self.end_run(run, output)
            return output
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _fetch_and_store_comments(
        self,
        pub: Any,
        channel: Any,
        max_count: int,
    ) -> list[PlatformComment]:
        platform = (pub.platform or "").lower()
        video_id = pub.platform_video_id
        if not video_id:
            return []

        raw_comments: list[Any] = []
        if platform == "youtube":
            raw_comments = await youtube_comments.fetch_video_comments(
                video_id,
                refresh_token=channel.youtube_refresh_token,
                max_results=max_count,
            )
        elif platform == "tiktok" and tiktok_is_connected(channel):
            raw_comments = await tiktok_comments.fetch_video_comments(channel, video_id, max_count)

        stored: list[PlatformComment] = []
        async with AsyncSessionFactory() as session:
            for raw in raw_comments:
                cid = getattr(raw, "platform_comment_id", "")
                existing = await session.execute(
                    select(PlatformComment).where(
                        PlatformComment.platform == platform,
                        PlatformComment.platform_comment_id == cid,
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                row = PlatformComment(
                    publication_id=pub.id,
                    platform=platform,
                    platform_comment_id=cid,
                    author_name=getattr(raw, "author_name", None),
                    text=getattr(raw, "text", ""),
                    published_at=getattr(raw, "published_at", None),
                    status="new",
                )
                session.add(row)
                stored.append(row)
            await session.commit()
            for row in stored:
                await session.refresh(row)
        return stored

    async def _apply_replies(
        self,
        pub: Any,
        channel: Any,
        analyses: list[dict[str, Any]],
        max_replies: int,
    ) -> int:
        sent = 0
        platform = (pub.platform or "").lower()
        for item in analyses:
            if sent >= max_replies:
                break
            if not item.get("needs_reply") or not item.get("reply_text"):
                continue
            cid = str(item.get("platform_comment_id", ""))
            reply_text = str(item["reply_text"])[:500]
            try:
                if platform == "youtube":
                    await youtube_comments.reply_to_comment(
                        cid,
                        reply_text,
                        refresh_token=channel.youtube_refresh_token,
                    )
                elif platform == "tiktok" and tiktok_is_connected(channel):
                    await tiktok_comments.reply_to_comment(channel, cid, reply_text)
                else:
                    continue
                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        select(PlatformComment).where(
                            PlatformComment.platform == platform,
                            PlatformComment.platform_comment_id == cid,
                        )
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        row.status = "replied"
                        row.reply_text = reply_text
                        row.replied_at = datetime.now(timezone.utc)
                        session.add(row)
                        await session.commit()
                sent += 1
            except Exception as e:
                logger.warning("Réponse commentaire %s échouée : %s", cid, e)
        return sent

    async def _mark_comments_processed(self, analyses: list[dict[str, Any]]) -> None:
        async with AsyncSessionFactory() as session:
            for item in analyses:
                cid = str(item.get("platform_comment_id", ""))
                status = str(item.get("status", "ignored"))
                result = await session.execute(
                    select(PlatformComment).where(PlatformComment.platform_comment_id == cid)
                )
                row = result.scalar_one_or_none()
                if not row:
                    continue
                if row.status == "replied":
                    continue
                row.status = status if status in ("ignored", "spam", "replied", "new") else "ignored"
                if row.status == "new":
                    row.status = "ignored"
                row.analysis = item
                session.add(row)
            await session.commit()

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
