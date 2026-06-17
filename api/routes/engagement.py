from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.agents.analytics_agent import AnalyticsAgent
from agent.agents.comments_agent import CommentsAgent
from agent.core.learning_context import load_channel_context

router = APIRouter(prefix="/api/v1/engagement", tags=["engagement"])


class EngagementRunResponse(BaseModel):
    analytics: dict[str, int] | None = None
    comments: dict[str, int] | None = None


class LearningContextResponse(BaseModel):
    channel_id: uuid.UUID
    summary: str
    version: int
    insights: list[dict]
    prompt_preview: str


@router.post("/run", response_model=EngagementRunResponse)
async def run_engagement_agents(
    analytics: bool = True,
    comments: bool = True,
    force_all: bool = True,
) -> EngagementRunResponse:
    """Déclenche manuellement les agents analytics et commentaires."""
    result = EngagementRunResponse()
    if analytics:
        result.analytics = await AnalyticsAgent().run_scheduled(force_all=force_all)
    if comments:
        result.comments = await CommentsAgent().run_scheduled(force_all=force_all)
    return result


@router.post("/publications/{publication_id}/analytics")
async def run_analytics_for_publication(publication_id: uuid.UUID) -> dict:
    try:
        return await AnalyticsAgent().run_for_publication(publication_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/publications/{publication_id}/comments")
async def run_comments_for_publication(publication_id: uuid.UUID) -> dict:
    try:
        return await CommentsAgent().run_for_publication(publication_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/pending-replies")
async def list_pending_replies(publication_id: uuid.UUID | None = None) -> list[dict]:
    """Réponses générées en attente de validation humaine (require_reply_review actif)."""
    return await CommentsAgent.list_pending_replies(publication_id)


@router.post("/comments/{comment_id}/approve-reply")
async def approve_pending_reply(comment_id: uuid.UUID) -> dict:
    try:
        return await CommentsAgent().approve_pending_reply(comment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/comments/{comment_id}/reject-reply")
async def reject_pending_reply(comment_id: uuid.UUID) -> dict:
    try:
        return await CommentsAgent().reject_pending_reply(comment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/channels/{channel_id}/learning-context", response_model=LearningContextResponse)
async def get_channel_learning_context(channel_id: uuid.UUID) -> LearningContextResponse:
    snapshot = await load_channel_context(channel_id)
    return LearningContextResponse(
        channel_id=snapshot.channel_id,
        summary=snapshot.summary,
        version=snapshot.version,
        insights=[
            {
                "id": i.id,
                "text": i.text,
                "source": i.source,
                "confidence": i.confidence,
                "active": i.active,
                "evidence": i.evidence,
            }
            for i in snapshot.insights
        ],
        prompt_preview=snapshot.format_for_prompt(),
    )
