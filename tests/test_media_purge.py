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
async def test_purge_project_files_removes_dirs_and_unpublished_videos(tmp_path, monkeypatch) -> None:
    project_id = uuid.uuid4()
    output_root, runs_root = tmp_path / "output", tmp_path / "runs"
    for root in (output_root, runs_root):
        (root / str(project_id) / "media").mkdir(parents=True)
    monkeypatch.setattr("agent.core.claude_studio.OUTPUT_ROOT", output_root)
    monkeypatch.setattr("studio.launcher.default_runs_dir", lambda: runs_root)
    local = tmp_path / "short_master.mp4"
    local.write_bytes(b"x")
    video = SimpleNamespace(id=uuid.uuid4(), storage_key=None, local_path=str(local), file_size_bytes=1)

    result = MagicMock()
    result.scalars.return_value.all.return_value = [video]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=None)
    with patch.object(cleanup, "AsyncSessionFactory", _session_factory(session)):
        report = await cleanup.purge_project_files(project_id)

    assert report.dirs_removed == 2 and report.videos_purged == 1 and report.projects_purged == 1
    assert not local.exists()
    assert not (output_root / str(project_id)).exists()
    assert not (runs_root / str(project_id)).exists()
    # Les vidéos publiées / programmées sont exclues de la sélection.
    query = str(session.execute.await_args_list[0].args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "publications.status IN ('scheduled', 'publishing', 'published')" in query
    assert "videos.file_purged_at IS NULL" in query


@pytest.mark.asyncio
async def test_finished_projects_purge_skips_active_and_recent(monkeypatch) -> None:
    project_id = uuid.uuid4()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [project_id]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    purged: list[uuid.UUID] = []

    async def fake_purge(pid):
        purged.append(pid)
        return cleanup.PurgeReport(dirs_removed=1, projects_purged=1)

    monkeypatch.setattr(cleanup, "purge_project_files", fake_purge)
    with patch.object(cleanup, "AsyncSessionFactory", _session_factory(session)):
        report = await cleanup._purge_finished_projects(datetime.now(UTC))

    assert purged == [project_id] and report.projects_purged == 1
    query = str(session.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "projects.updated_at <" in query
    assert "projects.status NOT IN ('running', 'queued', 'paused')" in query


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
