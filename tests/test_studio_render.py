from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import time

from studio.contracts import ContractError, TimelineClip
from studio.media import probe_media, record_credit
from studio.render import _segment_key, render_timeline


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


@pytest.mark.asyncio
async def test_render_reuses_unchanged_clip_segments(run_dir: Path) -> None:
    clip_image = {"media": "media/01.png", "start": 0, "end": 1.0, "motion": "zoom", "text": "Texte"}
    clip_video = {"media": "media/02.mp4", "start": 1.0, "end": 2.0, "video_offset": 0.2}
    first = await render_timeline(run_dir, _write_timeline(run_dir, [clip_image, clip_video]), Path("renders/v1.mp4"))
    assert (first["clips_encoded"], first["clips_reused"]) == (2, 0)

    segments = run_dir / ".render" / "segments"
    # Même durée mais décalé dans le temps (voix retouchée en amont) : repris ; offset vidéo changé : ré-encodé.
    clip_video_v2 = {**clip_video, "start": 0, "end": 1.0, "video_offset": 0.5}
    second = await render_timeline(
        run_dir,
        _write_timeline(run_dir, [clip_video_v2, {**clip_image, "start": 1.0, "end": 2.0}]),
        Path("renders/v2.mp4"),
    )
    assert (second["clips_encoded"], second["clips_reused"]) == (1, 1)
    # Le segment de v1 devenu inutile est supprimé : il ne reste que ceux du dernier rendu.
    assert len(list(segments.glob("*.mp4"))) == 2
    assert not list(segments.glob(".*.tmp.mp4"))
    assert abs((await probe_media(run_dir / "renders" / "v2.mp4"))["duration_s"] - 2.0) < 0.2

    # Un média refait sous le même nom (animation relancée, nouveau téléchargement) change de clé.
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=640x360", "-frames:v", "1", str(run_dir / "media" / "01.png"))
    third = await render_timeline(
        run_dir, _write_timeline(run_dir, [clip_image, {**clip_video_v2, "start": 1.0, "end": 2.0}]), Path("renders/v3.mp4")
    )
    assert (third["clips_encoded"], third["clips_reused"]) == (1, 1)


@pytest.mark.asyncio
async def test_render_failure_leaves_cache_clean(run_dir: Path) -> None:
    clip_ok = {"media": "media/02.mp4", "start": 0, "end": 1.0}
    await render_timeline(run_dir, _write_timeline(run_dir, [clip_ok, {"media": "media/01.png", "start": 1.0, "end": 2.0}]),
                          Path("renders/v1.mp4"))
    segments = run_dir / ".render" / "segments"
    before = sorted(segments.glob("*.mp4"))

    # Un mp4 corrompu : ffmpeg le refuse à l'ouverture (une image corrompue est, elle, refusée par verify_image).
    (run_dir / "media" / "bad.mp4").write_bytes(b"pas une video")
    with pytest.raises(RuntimeError, match="Rendu clip 1"):
        await render_timeline(run_dir, _write_timeline(run_dir, [clip_ok, {"media": "media/bad.mp4", "start": 1.0, "end": 2.0}]),
                              Path("renders/v2.mp4"))
    # Aucun segment partiel promu ni .tmp oublié ; les segments valides du rendu précédent sont intacts.
    assert sorted(segments.glob("*.mp4")) == before
    assert not list(segments.glob(".*.tmp.mp4"))


_IMAGE = {"media": "media/01.png", "start": 2.0, "end": 3.5, "motion": "zoom", "text": "Un mot"}
_VIDEO = {"media": "media/02.mp4", "start": 2.0, "end": 3.5, "video_offset": 1.0, "text": ""}


@pytest.mark.parametrize("base, change, same_key", [
    # Décalé dans le temps à durée égale, bruitage : sans effet sur l'image du segment.
    (_IMAGE, {"start": 7.0, "end": 8.5}, True),
    (_IMAGE, {"sfx": "whoosh"}, True),
    # Une image ignore `video_offset`, une vidéo ignore `motion` ; le placement d'un texte vide ne compte pas.
    (_IMAGE, {"video_offset": 3.0}, True),
    (_VIDEO, {"motion": "pan_left"}, True),
    (_VIDEO, {"text_position": "bottom"}, True),
    # Ce qui change l'image rend une autre clé.
    (_IMAGE, {"end": 4.0}, False),
    (_IMAGE, {"motion": "pan_right"}, False),
    (_IMAGE, {"text": "Autre"}, False),
    (_IMAGE, {"text_position": "bottom"}, False),
    (_VIDEO, {"video_offset": 2.0}, False),
])
def test_segment_key_depends_only_on_what_the_clip_renders(run_dir: Path, base: dict, change: dict, same_key: bool) -> None:
    src = run_dir / base["media"]
    key = _segment_key(TimelineClip(**base), src)
    assert (_segment_key(TimelineClip(**{**base, **change}), src) == key) is same_key


def test_segment_key_changes_with_the_source_file(run_dir: Path) -> None:
    src = run_dir / _IMAGE["media"]
    key = _segment_key(TimelineClip(**_IMAGE), src)
    src.write_bytes(src.read_bytes() + b"\0")
    assert _segment_key(TimelineClip(**_IMAGE), src) != key


@pytest.mark.asyncio
async def test_render_rejects_corrupt_image_before_encoding(run_dir: Path) -> None:
    """Un PNG tronqué ferait boucler `ffmpeg -loop 1` sans fin : refusé avant tout encodage."""
    good = (run_dir / "media" / "01.png").read_bytes()
    (run_dir / "media" / "bad.png").write_bytes(good[: len(good) // 2])
    timeline = _write_timeline(run_dir, [{"media": "media/bad.png", "start": 0, "end": 2.0}])
    started = time.monotonic()
    with pytest.raises(ContractError, match="image corrompue"):
        await render_timeline(run_dir, timeline, Path("renders/v1.mp4"))
    assert time.monotonic() - started < 10
    assert not (run_dir / ".render" / "segments").exists() or not list((run_dir / ".render" / "segments").iterdir())
