from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from studio.contracts import ContractError
from studio.media import probe_media, record_credit
from studio.render import render_timeline


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    media = tmp_path / "media"
    media.mkdir()
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=640x360", "-frames:v", "1", str(media / "01.png"))
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-t", "1", "-pix_fmt", "yuv420p",
            str(media / "02.mp4"))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-ar", "48000", str(tmp_path / "voice.wav"))
    words = [{"word": "Bonjour", "start": 0.1, "end": 0.8}, {"word": "test", "start": 0.9, "end": 1.6}]
    (tmp_path / "words.json").write_text(json.dumps(words), encoding="utf-8")
    record_credit(tmp_path, "media/01.png", {"source": "pexels", "attribution": "Photo par X via Pexels"})
    return tmp_path


def _write_timeline(run_dir: Path, clips: list[dict]) -> Path:
    path = run_dir / "timeline.json"
    path.write_text(json.dumps({"clips": clips}), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_render_timeline_produces_vertical_short(run_dir: Path) -> None:
    timeline = _write_timeline(run_dir, [
        {"media": "media/01.png", "start": 0, "end": 1.0, "motion": "zoom", "text": "Texte d'overlay"},
        # vidéo d'1 s placée sur un créneau plus long : elle doit boucler
        {"media": "media/02.mp4", "start": 1.0, "end": 2.0, "video_offset": 0.2},
    ])
    summary = await render_timeline(run_dir, timeline, Path("renders/v1.mp4"))

    out = run_dir / "renders" / "v1.mp4"
    info = await probe_media(out)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert info["has_audio"]
    assert abs(info["duration_s"] - 2.0) < 0.2
    assert summary["subtitles"] is True
    assert summary["credits"] == [{"media": "media/01.png", "source": "pexels", "attribution": "Photo par X via Pexels"}]
    assert (run_dir / "renders" / "v1.render.json").exists()
    assert not (run_dir / ".render" / "v1").exists()


@pytest.mark.asyncio
async def test_render_rejects_timeline_not_matching_voice(run_dir: Path) -> None:
    timeline = _write_timeline(run_dir, [{"media": "media/01.png", "start": 0, "end": 5.0}])
    with pytest.raises(ContractError, match="la voix"):
        await render_timeline(run_dir, timeline, Path("renders/v1.mp4"))


@pytest.mark.asyncio
async def test_render_rejects_paths_outside_run_dir(run_dir: Path) -> None:
    timeline = _write_timeline(run_dir, [{"media": "../evil.png", "start": 0, "end": 2.0}])
    with pytest.raises(ContractError, match="hors du run dir"):
        await render_timeline(run_dir, timeline, Path("renders/v1.mp4"))
