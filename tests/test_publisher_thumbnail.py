"""Tests miniature agent → publication YouTube."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.database import Project, Video
from agent.skills.publisher.executor import _resolve_youtube_thumbnail_path


@pytest.mark.asyncio
async def test_resolve_thumbnail_uses_agent_primary(tmp_path: Path) -> None:
    thumb_file = tmp_path / "agent_thumb.jpg"
    thumb_file.write_bytes(b"fake-jpeg")

    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        channel_id=uuid.uuid4(),
        title="Test",
        theme="histoire",
        config={
            "thumbnail": {"local_path": str(thumb_file), "primary": True},
        },
    )
    video = Video(
        id=uuid.uuid4(),
        project_id=project_id,
        video_type="long",
        local_path=str(tmp_path / "video.mp4"),
        duration_s=600.0,
    )

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=project)

    with patch(
        "agent.skills.publisher.executor.AsyncSessionFactory"
    ) as factory_mock:
        factory_mock.return_value.__aenter__.return_value = mock_session
        path = await _resolve_youtube_thumbnail_path(
            video,
            title="Titre test",
            theme="histoire",
            channel_config=ChannelRuntimeConfig(),
            output_dir=tmp_path,
        )

    assert path == thumb_file


@pytest.mark.asyncio
async def test_publish_youtube_calls_set_thumbnail_with_agent_path(tmp_path: Path) -> None:
    from agent.core.database import Channel, Publication
    from agent.skills.publisher.executor import _publish_youtube

    thumb_file = tmp_path / "primary.jpg"
    thumb_file.write_bytes(b"jpeg")
    project_id = uuid.uuid4()

    publication = Publication(
        id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        platform="youtube",
        title="Ma vidéo",
        description="Desc",
    )
    channel = Channel(
        id=publication.channel_id,
        slug="test",
        name="Test",
        theme_category="histoire",
        youtube_refresh_token="token",
    )
    video = Video(
        id=publication.video_id,
        project_id=project_id,
        video_type="long",
        local_path=str(tmp_path / "v.mp4"),
        storage_key="videos/v.mp4",
        duration_s=120.0,
    )
    project = Project(
        id=project_id,
        channel_id=channel.id,
        title="Ma vidéo",
        theme="histoire",
        config={"thumbnail": {"local_path": str(thumb_file), "primary": True}},
    )

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=project)
    mock_session.execute = AsyncMock()
    mock_session.scalar_one_or_none = MagicMock(return_value=channel)

    with (
        patch(
            "agent.skills.publisher.executor.resolve_local_path_for_upload",
            new_callable=AsyncMock,
            return_value=tmp_path / "v.mp4",
        ),
        patch(
            "agent.skills.publisher.youtube.upload_video",
            new_callable=AsyncMock,
            return_value="yt123",
        ),
        patch(
            "agent.skills.publisher.youtube.set_thumbnail",
            new_callable=AsyncMock,
        ) as set_thumb_mock,
        patch(
            "agent.skills.publisher.executor._mark_published",
            new_callable=AsyncMock,
            return_value=publication,
        ),
        patch(
            "agent.skills.publisher.executor.AsyncSessionFactory"
        ) as factory_mock,
        patch(
            "agent.skills.publisher.youtube_channel_manager.post_publish_hook",
            new_callable=AsyncMock,
        ),
        patch(
            "agent.skills.publisher.synthetic_disclosure.detect_realistic_synthetic_media",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        factory_mock.return_value.__aenter__.return_value = mock_session
        await _publish_youtube(
            publication,
            channel,
            ChannelRuntimeConfig(),
            video,
            "Ma vidéo",
            "Desc",
            ["tag"],
        )

    set_thumb_mock.assert_awaited_once()
    assert set_thumb_mock.await_args.args[1] == thumb_file
