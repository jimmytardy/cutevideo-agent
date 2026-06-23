"""Contexte d'annulation coopérative du pipeline (flag Redis + ContextVar)."""

from __future__ import annotations

import asyncio
import uuid
from contextvars import ContextVar, Token

from agent.core.queue import queue

_current_project_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_project_id", default=None
)


def bind_project(project_id: uuid.UUID) -> Token[uuid.UUID | None]:
    return _current_project_id.set(project_id)


def unbind_project(token: Token[uuid.UUID | None]) -> None:
    _current_project_id.reset(token)


async def raise_if_pipeline_cancelled() -> None:
    project_id = _current_project_id.get()
    if project_id is None:
        return
    if await queue.is_pipeline_cancel_requested(str(project_id)):
        raise asyncio.CancelledError()
