from __future__ import annotations

import uuid

import pytest

from agent.skills.media.media_library import (
    LIBRARY_POOL,
    LIBRARY_SELECTED,
    promote_to_pool,
)
from agent.core.database import MediaAsset


def test_promote_to_pool_rejects_low_score() -> None:
    asset = MediaAsset(
        project_id=uuid.uuid4(),
        selected=True,
        relevance_score=50,
        library_status=LIBRARY_SELECTED,
    )
    promote_to_pool(asset, pool_min_score=70)
    assert asset.library_status == "rejected"
    assert asset.selected is False


def test_promote_to_pool_accepts_high_score() -> None:
    asset = MediaAsset(
        project_id=uuid.uuid4(),
        selected=True,
        relevance_score=85,
        library_status=LIBRARY_SELECTED,
    )
    promote_to_pool(asset, pool_min_score=70)
    assert asset.library_status == LIBRARY_POOL
    assert asset.selected is False
