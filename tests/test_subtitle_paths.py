from __future__ import annotations

import uuid
from pathlib import Path

from agent.core.final_preview import subtitles_available_for_video, video_is_streamable
from agent.core.subtitle_paths import resolve_project_srt_path


def test_resolve_project_srt_prefers_video_specific(tmp_path: Path, monkeypatch) -> None:
    project_id = uuid.uuid4()
    video_id = uuid.uuid4()
    project_dir = tmp_path / "tmp" / str(project_id)
    project_dir.mkdir(parents=True)
    generic = project_dir / "subtitles.srt"
    generic.write_text("generic", encoding="utf-8")
    specific = project_dir / f"subtitles_{video_id}.srt"
    specific.write_text("specific", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    resolved = resolve_project_srt_path(project_id, video_id=video_id)
    assert resolved is not None
    assert resolved.resolve() == specific.resolve()


def test_resolve_project_srt_falls_back_to_generic(tmp_path: Path, monkeypatch) -> None:
    project_id = uuid.uuid4()
    project_dir = tmp_path / "tmp" / str(project_id)
    project_dir.mkdir(parents=True)
    generic = project_dir / "subtitles.srt"
    generic.write_text("generic", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    resolved = resolve_project_srt_path(project_id)
    assert resolved is not None
    assert resolved.resolve() == generic.resolve()


def test_subtitles_not_offered_for_short_master(tmp_path: Path, monkeypatch) -> None:
    project_id = uuid.uuid4()
    project_dir = tmp_path / "tmp" / str(project_id)
    project_dir.mkdir(parents=True)
    (project_dir / "subtitles.srt").write_text("srt", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    video = type("Video", (), {"video_type": "short_master", "id": uuid.uuid4()})()
    assert subtitles_available_for_video(video, project_id) is False


def test_video_is_streamable_with_local_file(tmp_path: Path) -> None:
    video_file = tmp_path / "clip.mp4"
    video_file.write_bytes(b"x")
    video = type("Video", (), {"local_path": str(video_file), "storage_key": None})()
    assert video_is_streamable(video) is True
