from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import AgentRun, AsyncSessionFactory, User, get_db
from api.authorization import get_user_project
from api.deps import get_current_user
from api.models import AgentRunResponse

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

# Flux SSE de la trace d'un sous-agent : relecture de AgentRun.log (écrite par le worker).
LOG_POLL_INTERVAL_S = 1.0
LOG_PING_INTERVAL_S = 15.0


@router.get("/runs/{project_id}", response_model=list[AgentRunResponse])
async def list_agent_runs(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AgentRun]:
    await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.project_id == project_id)
        .order_by(AgentRun.started_at.desc())
    )
    return list(result.scalars().all())


async def _read_log(session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(AgentRun.log, AgentRun.status).where(
                AgentRun.id == run_id, AgentRun.project_id == project_id
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return {"lines": list(row.log or []), "running": row.status == "running"}


@router.get("/runs/{project_id}/{run_id}/log", response_model=None)
async def get_agent_run_log(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Trace d'exécution d'un sous-agent : `{lines, running}`."""
    await get_user_project(db, project_id, current_user)
    data = await _read_log(db, project_id, run_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exécution introuvable")
    return data


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/runs/{project_id}/{run_id}/log/stream", response_model=None)
async def stream_agent_run_log(
    request: Request,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE : `history` {lines, running} à la connexion, puis `line` par ligne nouvelle ou modifiée, `done` à la fin."""
    await get_user_project(db, project_id, current_user)
    if await _read_log(db, project_id, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exécution introuvable")
    # La session injectée ne se ferme qu'après la réponse : sans ça, chaque flux (plusieurs minutes)
    # garderait une connexion du pool « idle in transaction ». La boucle ouvre ses propres sessions.
    await db.close()

    async def events() -> AsyncIterator[str]:
        sent: list[str] | None = None
        last_ping = time.monotonic()
        while not await request.is_disconnected():
            async with AsyncSessionFactory() as session:
                data = await _read_log(session, project_id, run_id)
            if data is None:
                yield _sse("done", {})
                return
            lines = data["lines"]
            # Trace tronquée par le début (plafond de taille) : on renvoie tout plutôt qu'un diff décalé.
            if sent is None or len(lines) < len(sent) or (sent and lines[0] != sent[0]):
                yield _sse("history", data)
            else:
                for i, line in enumerate(lines):
                    if i >= len(sent) or sent[i] != line:
                        yield _sse("line", {"line": line})
            sent = lines
            if not data["running"]:
                yield _sse("done", {})
                return
            if time.monotonic() - last_ping >= LOG_PING_INTERVAL_S:
                last_ping = time.monotonic()
                yield ": ping\n\n"
            await asyncio.sleep(LOG_POLL_INTERVAL_S)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
