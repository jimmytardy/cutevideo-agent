"""Purge de rétention : dossiers Studio et fichiers locaux des vidéos."""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.scheduler import cleanup


def _session_factory(session: AsyncMock) -> MagicMock:
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=session)
    factory.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=factory)


@pytest.mark.asyncio
async def test_old_project_dirs_include_studio_output_and_run_dir(tmp_path, monkeypatch) -> None:
    project_id = uuid.uuid4()
    output_root, runs_root = tmp_path / "output", tmp_path / "runs"
    for root in (output_root, runs_root):
        (root / str(project_id) / "media").mkdir(parents=True)
    monkeypatch.setattr("agent.core.claude_studio.OUTPUT_ROOT", output_root)
    monkeypatch.setattr("studio.launcher.default_runs_dir", lambda: runs_root)

    result = MagicMock()
    result.scalars.return_value.all.return_value = [project_id]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    with patch.object(cleanup, "AsyncSessionFactory", _session_factory(session)):
        report = await cleanup._purge_old_project_dirs(datetime.now(UTC))

    assert report.dirs_removed == 2
    assert not (output_root / str(project_id)).exists()
    assert not (runs_root / str(project_id)).exists()


@pytest.mark.asyncio
async def test_purge_video_removes_local_copy(tmp_path) -> None:
    local = tmp_path / "short_master.mp4"
    local.write_bytes(b"x")
    video = SimpleNamespace(id=uuid.uuid4(), storage_key=None, local_path=str(local), file_size_bytes=1)
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    with patch.object(cleanup, "AsyncSessionFactory", _session_factory(session)):
        report = await cleanup.purge_video_files([video])  # type: ignore[list-item]

    assert not local.exists()
    assert report.errors == []
