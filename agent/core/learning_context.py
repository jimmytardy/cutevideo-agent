from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import AsyncSessionFactory, ChannelLearningContext

logger = logging.getLogger(__name__)

MAX_ACTIVE_INSIGHTS = 30

LEARNING_CONTEXT_BLOCK = """
RETOURS AUDIENCE ET ANALYTICS (à intégrer obligatoirement dans cette production) :
{learning_context_prompt}
"""


@dataclass
class InsightItem:
    id: str
    text: str
    source: str
    confidence: float
    active: bool = True
    created_at: str = ""
    invalidated_at: str | None = None
    evidence: str = ""


@dataclass
class ChannelContextSnapshot:
    channel_id: uuid.UUID
    summary: str
    insights: list[InsightItem] = field(default_factory=list)
    version: int = 1

    def format_for_prompt(self) -> str:
        if not self.summary and not self.active_insights():
            return "Aucun retour audience ou analytics enregistré pour cette chaîne."

        lines: list[str] = []
        if self.summary:
            lines.append(f"Résumé : {self.summary}")
        active = self.active_insights()
        if active:
            lines.append("Insights actifs :")
            for item in active[:15]:
                lines.append(
                    f"- [{item.source}, confiance {item.confidence:.0%}] {item.text}"
                )
        return "\n".join(lines)

    def active_insights(self) -> list[InsightItem]:
        return [i for i in self.insights if i.active]


def scheduled_analysis_hour(publication_id: uuid.UUID) -> int:
    """Heure UTC stable (0-23) pour l'analyse analytics quotidienne."""
    return publication_id.int % 24


def scheduled_comments_hour(publication_id: uuid.UUID) -> int:
    """Heure UTC décalée pour le traitement des commentaires."""
    return (publication_id.int + 12) % 24


def format_learning_block(snapshot: ChannelContextSnapshot | None) -> str:
    prompt = (
        snapshot.format_for_prompt()
        if snapshot
        else "Aucun retour audience ou analytics enregistré pour cette chaîne."
    )
    return LEARNING_CONTEXT_BLOCK.format(learning_context_prompt=prompt)


async def load_channel_context(channel_id: uuid.UUID) -> ChannelContextSnapshot:
    async with AsyncSessionFactory() as session:
        row = await _get_or_create_context(session, channel_id)
        return _row_to_snapshot(row)


async def save_channel_context(
    channel_id: uuid.UUID,
    summary: str,
    insights: list[dict[str, Any]],
) -> ChannelContextSnapshot:
    normalized = _normalize_insights(insights)
    async with AsyncSessionFactory() as session:
        row = await _get_or_create_context(session, channel_id)
        row.summary = summary[:4000] if summary else ""
        row.insights = normalized
        row.version = (row.version or 0) + 1
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _row_to_snapshot(row)


async def merge_llm_context_update(
    channel_id: uuid.UUID,
    llm_payload: dict[str, Any],
) -> ChannelContextSnapshot:
    """Fusionne une mise à jour Claude : nouveaux insights, invalidations, résumé."""
    current = await load_channel_context(channel_id)
    insight_map = {i.id: i for i in current.insights}

    for inv in llm_payload.get("invalidate_insight_ids", []) or []:
        inv_id = str(inv)
        if inv_id in insight_map:
            insight_map[inv_id].active = False
            insight_map[inv_id].invalidated_at = datetime.now(timezone.utc).isoformat()

    for raw in llm_payload.get("new_insights", []) or []:
        if not isinstance(raw, dict) or not raw.get("text"):
            continue
        item = InsightItem(
            id=str(raw.get("id") or uuid.uuid4()),
            text=str(raw["text"])[:500],
            source=str(raw.get("source", "analytics")),
            confidence=float(raw.get("confidence", 0.6)),
            active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
            evidence=str(raw.get("evidence", ""))[:300],
        )
        insight_map[item.id] = item

    for upd in llm_payload.get("update_insights", []) or []:
        if not isinstance(upd, dict):
            continue
        iid = str(upd.get("id", ""))
        if iid not in insight_map:
            continue
        existing = insight_map[iid]
        if upd.get("text"):
            existing.text = str(upd["text"])[:500]
        if "confidence" in upd:
            existing.confidence = float(upd["confidence"])
        if upd.get("active") is False:
            existing.active = False
            existing.invalidated_at = datetime.now(timezone.utc).isoformat()

    active = [i for i in insight_map.values() if i.active]
    active.sort(key=lambda x: x.confidence, reverse=True)
    kept_ids = {i.id for i in active[:MAX_ACTIVE_INSIGHTS]}
    for iid, item in insight_map.items():
        if iid not in kept_ids and item.active:
            item.active = False
            item.invalidated_at = datetime.now(timezone.utc).isoformat()

    summary = str(llm_payload.get("summary") or current.summary)
    insights_json = [_insight_to_dict(i) for i in insight_map.values()]
    return await save_channel_context(channel_id, summary, insights_json)


async def _get_or_create_context(
    session: AsyncSession,
    channel_id: uuid.UUID,
) -> ChannelLearningContext:
    result = await session.execute(
        select(ChannelLearningContext).where(ChannelLearningContext.channel_id == channel_id)
    )
    row = result.scalar_one_or_none()
    if row:
        return row
    row = ChannelLearningContext(
        channel_id=channel_id,
        summary="",
        insights=[],
        version=1,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def _normalize_insights(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, InsightItem):
            out.append(_insight_to_dict(item))
        elif isinstance(item, dict) and item.get("text"):
            out.append(
                {
                    "id": str(item.get("id") or uuid.uuid4()),
                    "text": str(item["text"])[:500],
                    "source": str(item.get("source", "analytics")),
                    "confidence": float(item.get("confidence", 0.5)),
                    "active": bool(item.get("active", True)),
                    "created_at": item.get("created_at")
                    or datetime.now(timezone.utc).isoformat(),
                    "invalidated_at": item.get("invalidated_at"),
                    "evidence": str(item.get("evidence", ""))[:300],
                }
            )
    return out


def _insight_to_dict(item: InsightItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "text": item.text,
        "source": item.source,
        "confidence": item.confidence,
        "active": item.active,
        "created_at": item.created_at,
        "invalidated_at": item.invalidated_at,
        "evidence": item.evidence,
    }


def _row_to_snapshot(row: ChannelLearningContext) -> ChannelContextSnapshot:
    insights: list[InsightItem] = []
    for raw in row.insights or []:
        if not isinstance(raw, dict):
            continue
        insights.append(
            InsightItem(
                id=str(raw.get("id", "")),
                text=str(raw.get("text", "")),
                source=str(raw.get("source", "")),
                confidence=float(raw.get("confidence", 0.5)),
                active=bool(raw.get("active", True)),
                created_at=str(raw.get("created_at", "")),
                invalidated_at=raw.get("invalidated_at"),
                evidence=str(raw.get("evidence", "")),
            )
        )
    return ChannelContextSnapshot(
        channel_id=row.channel_id,
        summary=row.summary or "",
        insights=insights,
        version=row.version or 1,
    )
