"""Routes projet : cas d'erreur."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.routes import projects


@pytest.mark.asyncio
async def test_queue_status_unknown_project_is_404() -> None:
    """La variable locale ne doit pas masquer `fastapi.status` (UnboundLocalError → 500)."""
    with (
        patch.object(projects, "get_user_project", AsyncMock()),
        patch.object(projects, "get_queue_status", AsyncMock(side_effect=ValueError("introuvable"))),
        pytest.raises(HTTPException) as exc,
    ):
        await projects.get_project_queue_status(uuid.uuid4(), db=AsyncMock(), current_user=AsyncMock())
    assert exc.value.status_code == 404
