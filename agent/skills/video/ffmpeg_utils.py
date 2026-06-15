from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

import ffmpeg

from agent.core.config import load_agent_config
from agent.core.database import AudioFile, MediaAsset

logger = logging.getLogger(__name__)

MOOD_TO_TRANSITION: dict[str, str] = {
    "dramatique": "dissolve",
    "tension": "dissolve",
    "mysterieux": "dissolve",
    "energique": "wipeleft",
    "humoristique": "wiperight",
}


def _load_transition_config() -> dict[str, float | bool]:
    cfg = load_agent_config().get("video", {}).get("transitions", {})
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "duration_s": float(cfg.get("duration_s", 0.4)),
    }


def _transition_for_mood(mood: str) -> str:
    return MOOD_TO_TRANSITION.get(mood.lower().strip(), "fade")


async def _probe_clip_duration(clip_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(clip_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return float(stdout.decode().strip() or "0")


def _transition_overlap_duration(clip_count: int) -> float:
    """Durée perdue par les transitions xfade entre clips consécutifs."""
    if clip_count <= 1:
        return 0.0
    trans_cfg = _load_transition_config()
    if not trans_cfg["enabled"]:
        return 0.0
    return (clip_count - 1) * float(trans_cfg["duration_s"])


def _video_pad_filter_suffix(pad_s: float) -> str:
    if pad_s <= 0.01:
        return ""
    return f",tpad=stop_mode=clone:stop_duration={pad_s:.3f}"


async def _resolve_audio_duration(
    audio_path: str,
    *,
    fallback: float | None = None,
) -> float:
    try:
        duration = await _probe_clip_duration(Path(audio_path))
        if duration > 0:
            return duration
    except (OSError, ValueError, RuntimeError):
        pass
    if fallback is not None and fallback > 0:
        return fallback
    return 0.0


async def _mux_video_with_narration(
    video_path: Path,
    audio_path: str,
    output_path: Path,
    *,
    audio_duration: float | None = None,
    vf_prefix: str | None = None,
    preset: str = "fast",
) -> None:
    """Assemble vidéo + narration : la durée audio fait foi, la vidéo est prolongée si besoin."""
    resolved_audio = audio_duration
    if resolved_audio is None or resolved_audio <= 0:
        resolved_audio = await _resolve_audio_duration(audio_path)
    if resolved_audio <= 0:
        raise RuntimeError(f"Durée audio invalide pour {audio_path}")

    video_duration = await _probe_clip_duration(video_path)
    pad_s = max(0.0, resolved_audio - video_duration)

    base_vf = vf_prefix if vf_prefix and vf_prefix != "null" else ""
    if base_vf:
        vf = f"{base_vf}{_video_pad_filter_suffix(pad_s)}"
        vf_args = ["-vf", vf]
    elif pad_s > 0.01:
        vf_args = ["-vf", f"tpad=stop_mode=clone:stop_duration={pad_s:.3f}"]
    else:
        vf_args = []

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", audio_path,
        *vf_args,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-crf", "22", "-preset", preset,
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-t", f"{resolved_audio:.3f}",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)


async def _concat_clips_with_transitions(
    clips: list[Path],
    output_path: Path,
    *,
    transition_type: str = "fade",
) -> None:
    """Concatène des clips vidéo avec transitions xfade."""
    if len(clips) == 1:
        cmd = ["ffmpeg", "-y", "-i", str(clips[0]), "-c", "copy", str(output_path)]
        await _run_ffmpeg(cmd)
        return

    trans_cfg = _load_transition_config()
    if not trans_cfg["enabled"]:
        concat_file = output_path.parent / f"{output_path.stem}_concat.txt"
        concat_file.write_text(
            "\n".join(f"file '{p.resolve()}'" for p in clips),
            encoding="utf-8",
        )
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
        ]
        await _run_ffmpeg(cmd)
        return

    duration_s = float(trans_cfg["duration_s"])
    current = clips[0]
    for i in range(1, len(clips)):
        step_out = output_path.parent / f"{output_path.stem}_xf{i}.mp4"
        from agent.skills.video.transitions import TransitionType, add_transition

        ttype = TransitionType(transition_type)
        await add_transition(current, clips[i], step_out, transition=ttype, duration_s=duration_s)
        current = step_out
    if current != output_path:
        cmd = ["ffmpeg", "-y", "-i", str(current), "-c", "copy", str(output_path)]
        await _run_ffmpeg(cmd)

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 25
VIDEO_BITRATE = "8M"
AUDIO_BITRATE = "192k"
AUDIO_SAMPLE_RATE = 48000


async def assemble_long_video(
    media_assets: list[MediaAsset],
    audio_files: list[AudioFile],
    output_path: Path,
    project_id: uuid.UUID,
    min_image_duration: int = 4,
    segment_durations: dict[int, float] | None = None,
    segment_meta: dict[int, dict] | None = None,
    segment_beat_timelines: dict[int, list] | None = None,
) -> float:
    """Assemble les images + audio en vidéo longue 1920x1080."""
    tmp_dir = Path(f"./tmp/{project_id}/assembly")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image_by_order: dict[int, list[str]] = {}
    video_clip_by_order: dict[int, str] = {}
    for asset in media_assets:
        if not asset.local_path or not Path(asset.local_path).exists():
            continue
        order = asset.segment_order or 0
        if (asset.asset_type or "image") == "video":
            if order not in video_clip_by_order:
                video_clip_by_order[order] = asset.local_path
        else:
            image_by_order.setdefault(order, []).append(asset.local_path)

    audio_by_order: dict[int, AudioFile] = {
        (af.segment_order or 0): af for af in audio_files if af.local_path
    }
    meta = segment_meta or {}

    visual_orders = set(image_by_order) | set(video_clip_by_order)
    audio_only_orders = {
        order
        for order, af in audio_by_order.items()
        if order not in visual_orders and meta.get(order, {}).get("visual_optional")
    }
    all_orders = sorted(visual_orders | audio_only_orders)
    video_segments: list[Path] = []
    for order in all_orders:
        seg_path = tmp_dir / f"segment_{order:02d}.mp4"
        audio_file = audio_by_order.get(order)
        seg_info = meta.get(order, {})
        strip_audio = seg_info.get("strip_source_audio", True)
        if order in audio_only_orders and audio_file:
            duration = float(audio_file.duration_s or seg_info.get("duration_s", 30))
            await _create_audio_only_segment(
                audio_file.local_path,
                duration,
                seg_path,
                on_screen_text=str(seg_info.get("on_screen_text", "")),
                width=VIDEO_WIDTH,
                height=VIDEO_HEIGHT,
            )
        elif order in video_clip_by_order:
            await _normalize_video_clip(
                Path(video_clip_by_order[order]), audio_file, seg_path,
                width=VIDEO_WIDTH, height=VIDEO_HEIGHT,
                strip_source_audio=strip_audio,
            )
        else:
            images = image_by_order[order]
            mood = str(seg_info.get("mood", "calme"))
            beat_timeline = (segment_beat_timelines or {}).get(order)
            if beat_timeline and audio_file:
                await _create_long_segment_beats(
                    beat_timeline,
                    audio_file.local_path,
                    seg_path,
                    mood=mood,
                )
            elif audio_file:
                audio_duration = float(audio_file.duration_s or 0)
                overlap = _transition_overlap_duration(len(images))
                target_visual = audio_duration + overlap
                img_duration = max(target_visual / len(images), float(min_image_duration))
                await _create_segment(
                    images,
                    audio_file.local_path,
                    img_duration,
                    seg_path,
                    mood=mood,
                    audio_duration=audio_duration,
                )
            else:
                silent_duration = float((segment_durations or {}).get(order, min_image_duration * len(images)))
                img_duration = max(silent_duration / len(images), float(min_image_duration))
                await _create_silent_segment(
                    images, img_duration, seg_path, on_screen_text="", mood=mood
                )
        video_segments.append(seg_path)

    if not video_segments:
        raise RuntimeError("Aucun segment vidéo à assembler")

    concat_list = tmp_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{seg.resolve()}'" for seg in video_segments),
        encoding="utf-8",
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:v", "libx264", "-crf", "22", "-preset", "medium",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)

    _assert_audio_stream(output_path)

    try:
        probe = ffmpeg.probe(str(output_path))
        duration = float(probe["format"]["duration"])
    except Exception as exc:
        raise RuntimeError(f"Impossible de sonder la vidéo assemblée {output_path}: {exc}") from exc
    logger.info("Vidéo longue assemblée : %.1f s → %s", duration, output_path)
    return duration


async def assemble_vertical_short(
    media_assets: list[MediaAsset],
    audio_files: list[AudioFile],
    output_path: Path,
    project_id: uuid.UUID,
    min_image_duration: int = 3,
    segment_meta: dict[int, dict] | None = None,
    segment_beat_timelines: dict[int, list] | None = None,
) -> float:
    """Assemble un short 9:16 depuis images + audio optionnel."""
    tmp_dir = Path(f"./tmp/{project_id}/assembly_vertical")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image_by_order: dict[int, list[str]] = {}
    video_clip_by_order: dict[int, str] = {}
    for asset in media_assets:
        if not asset.local_path or not Path(asset.local_path).exists():
            continue
        order = asset.segment_order or 0
        if (asset.asset_type or "image") == "video":
            if order not in video_clip_by_order:
                video_clip_by_order[order] = asset.local_path
        else:
            image_by_order.setdefault(order, []).append(asset.local_path)

    audio_by_order: dict[int, AudioFile] = {
        (af.segment_order or 0): af for af in audio_files if af.local_path
    }

    video_segments: list[Path] = []
    meta = segment_meta or {}

    visual_orders = set(image_by_order) | set(video_clip_by_order)
    audio_only_orders = {
        order
        for order, af in audio_by_order.items()
        if order not in visual_orders and meta.get(order, {}).get("visual_optional")
    }

    for order in sorted(visual_orders | audio_only_orders):
        seg_path = tmp_dir / f"segment_{order:02d}.mp4"
        audio_file = audio_by_order.get(order)
        seg_info = meta.get(order, {})
        on_screen = str(seg_info.get("on_screen_text", ""))

        if order in audio_only_orders and audio_file:
            duration = float(audio_file.duration_s or seg_info.get("duration_s", 30))
            await _create_vertical_audio_only_segment(
                audio_file.local_path,
                duration,
                seg_path,
                on_screen,
            )
        elif order in video_clip_by_order:
            strip_audio = seg_info.get("strip_source_audio", True)
            await _normalize_video_clip(
                Path(video_clip_by_order[order]), audio_file, seg_path,
                width=1080, height=1920,
                strip_source_audio=strip_audio,
            )
        else:
            images = image_by_order[order]
            target_d = float(seg_info.get("duration_s", min_image_duration * len(images)))
            beat_timeline = (segment_beat_timelines or {}).get(order)
            if beat_timeline and audio_file:
                await _create_vertical_segment_beats(
                    beat_timeline,
                    audio_file.local_path,
                    seg_path,
                )
            elif audio_file:
                audio_duration = float(audio_file.duration_s or target_d)
                img_duration = max(audio_duration / len(images), float(min_image_duration))
                await _create_vertical_segment(
                    images,
                    audio_file.local_path,
                    img_duration,
                    seg_path,
                    on_screen,
                    audio_duration=audio_duration,
                )
            else:
                img_duration = max(target_d / len(images), float(min_image_duration))
                await _create_vertical_silent_segment(images, img_duration, seg_path, on_screen)

        video_segments.append(seg_path)

    if not video_segments:
        raise RuntimeError("Aucun segment vertical à assembler")

    concat_list = tmp_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{seg.resolve()}'" for seg in video_segments),
        encoding="utf-8",
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:v", "libx264", "-crf", "22", "-preset", "medium",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)

    _assert_audio_stream(output_path)

    try:
        probe = ffmpeg.probe(str(output_path))
        return float(probe["format"]["duration"])
    except Exception as exc:
        raise RuntimeError(f"Impossible de sonder le short vertical {output_path}: {exc}") from exc


async def _create_vertical_segment(
    image_paths: list[str],
    audio_path: str,
    img_duration: float,
    output_path: Path,
    on_screen_text: str,
    *,
    audio_duration: float | None = None,
) -> None:
    from agent.skills.video.ken_burns import apply_ken_burns_vertical

    clips: list[Path] = []
    for i, img_path in enumerate(image_paths):
        clip_path = output_path.parent / f"{output_path.stem}_img{i}.mp4"
        pan_dir = (-1) ** i if i > 0 else 0
        await apply_ken_burns_vertical(
            Path(img_path), clip_path, duration_s=img_duration, pan_direction=pan_dir
        )
        clips.append(clip_path)

    concat_file = output_path.parent / f"{output_path.stem}_imgs.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in clips),
        encoding="utf-8",
    )

    visual_path = output_path.parent / f"{output_path.stem}_visual.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c", "copy",
        str(visual_path),
    ]
    await _run_ffmpeg(cmd)

    vf = _text_overlay_filter(on_screen_text) if on_screen_text else None
    await _mux_video_with_narration(
        visual_path,
        audio_path,
        output_path,
        audio_duration=audio_duration,
        vf_prefix=vf,
    )


async def _create_vertical_silent_segment(
    image_paths: list[str],
    img_duration: float,
    output_path: Path,
    on_screen_text: str,
) -> None:
    from agent.skills.video.ken_burns import apply_ken_burns_vertical

    clips: list[Path] = []
    for i, img_path in enumerate(image_paths):
        clip_path = output_path.parent / f"{output_path.stem}_img{i}.mp4"
        pan_dir = (-1) ** i if i > 0 else 0
        await apply_ken_burns_vertical(
            Path(img_path), clip_path, duration_s=img_duration, pan_direction=pan_dir
        )
        clips.append(clip_path)

    concat_file = output_path.parent / f"{output_path.stem}_imgs.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in clips),
        encoding="utf-8",
    )

    total_d = img_duration * len(image_paths)
    vf = _text_overlay_filter(on_screen_text) if on_screen_text else "null"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono",
        "-vf", vf,
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-t", str(total_d),
        "-shortest",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)


async def _create_silent_segment(
    image_paths: list[str],
    img_duration: float,
    output_path: Path,
    on_screen_text: str,
    mood: str = "calme",
) -> None:
    from agent.skills.video.ken_burns import apply_ken_burns

    clips: list[Path] = []
    for i, img_path in enumerate(image_paths):
        clip_path = output_path.parent / f"{output_path.stem}_img{i}.mp4"
        pan_dir = (-1) ** i if i > 0 else 0
        await apply_ken_burns(
            Path(img_path), clip_path, duration_s=img_duration, pan_direction=pan_dir
        )
        clips.append(clip_path)

    visual_path = output_path.parent / f"{output_path.stem}_visual.mp4"
    await _concat_clips_with_transitions(
        clips, visual_path, transition_type=_transition_for_mood(mood)
    )
    total_d = img_duration * len(image_paths)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(visual_path),
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-t", str(total_d),
        "-shortest",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)


async def _create_audio_only_segment(
    audio_path: str,
    duration: float,
    output_path: Path,
    on_screen_text: str,
    *,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
) -> None:
    resolved_duration = await _resolve_audio_duration(audio_path, fallback=duration)
    vf = _landscape_text_overlay_filter(on_screen_text)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s={width}x{height}:d={resolved_duration}",
        "-i", audio_path,
        "-vf", vf,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-t", f"{resolved_duration:.3f}",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)


async def _create_vertical_audio_only_segment(
    audio_path: str,
    duration: float,
    output_path: Path,
    on_screen_text: str,
) -> None:
    resolved_duration = await _resolve_audio_duration(audio_path, fallback=duration)
    vf = _text_overlay_filter(on_screen_text) if on_screen_text else "scale=1080:1920"
    if on_screen_text and "scale=" not in vf:
        vf = f"scale=1080:1920,{vf}"
    elif not on_screen_text:
        vf = "scale=1080:1920"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s=1080x1920:d={resolved_duration}",
        "-i", audio_path,
        "-vf", vf,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-t", f"{resolved_duration:.3f}",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )


def build_multi_drawtext_filter(
    placements: list,
    *,
    font_name: str = "DejaVu Sans",
) -> str | None:
    if not placements:
        return None
    filters: list[str] = []
    for placement in placements:
        safe = _escape_drawtext(str(placement.text))[:40]
        box = (
            ":box=1:boxcolor=black@0.6:boxborderw=6"
            if getattr(placement, "box", True)
            else ""
        )
        x_norm = float(placement.x_norm)
        y_norm = float(placement.y_norm)
        fontsize = int(getattr(placement, "fontsize", 36))
        filters.append(
            f"drawtext=font='{font_name}':text='{safe}':fontsize={fontsize}:"
            f"fontcolor=white:borderw=2:bordercolor=black@0.8"
            f"{box}:"
            f"x='(w*{x_norm})-(text_w/2)':y='(h*{y_norm})-(text_h/2)'"
        )
    return ",".join(filters)


def _single_beat_text_filter(
    text: str,
    *,
    vertical: bool,
    visual_type: str = "",
    font_name: str = "DejaVu Sans",
) -> str | None:
    if not text:
        return None
    safe = _escape_drawtext(text)[:80]
    if visual_type in ("quote_card", "statistic_highlight"):
        y_expr = "(h-text_h)/2"
        fontsize = 48 if not vertical else 42
    else:
        y_expr = "h*0.82" if not vertical else "h*0.75"
        fontsize = 44 if not vertical else 38
    return (
        f"drawtext=font='{font_name}':text='{safe}':fontsize={fontsize}:fontcolor=white:"
        f"box=1:boxcolor=black@0.65:boxborderw=6:borderw=2:bordercolor=black:"
        f"x=(w-text_w)/2:y={y_expr}"
    )


async def _apply_vf_to_clip(input_clip: Path, output_clip: Path, vf_filter: str) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_clip),
        "-vf", vf_filter,
        "-an",
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        str(output_clip),
    ]
    await _run_ffmpeg(cmd)


async def _apply_beat_text_overlay(
    clip_path: Path,
    entry: Any,
    *,
    vertical: bool,
    font_name: str = "DejaVu Sans",
) -> Path:
    layout = getattr(entry, "text_layout", ()) or ()
    if layout:
        vf = build_multi_drawtext_filter(list(layout), font_name=font_name)
    else:
        on_screen = getattr(entry, "on_screen_text", "") or ""
        visual_type = getattr(getattr(entry, "beat", None), "visual_type", "")
        vf = _single_beat_text_filter(
            on_screen,
            vertical=vertical,
            visual_type=visual_type,
            font_name=font_name,
        )
    if not vf:
        return clip_path
    overlaid = clip_path.parent / f"{clip_path.stem}_txt.mp4"
    await _apply_vf_to_clip(clip_path, overlaid, vf)
    return overlaid


def _landscape_text_overlay_filter(text: str) -> str:
    if not text:
        return "null"
    safe = text.replace("'", "\\'").replace(":", "\\:")[:120]
    return (
        f"drawtext=text='{safe}':fontsize=48:fontcolor=white:"
        "x=(w-text_w)/2:y=(h-text_h)/2:borderw=2:bordercolor=black"
    )


def _text_overlay_filter(text: str) -> str:
    if not text:
        return "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    safe = text.replace("'", "\\'").replace(":", "\\:")[:80]
    return (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe}':fontsize=42:fontcolor=white:borderw=2:bordercolor=black:"
        f"x=(w-text_w)/2:y=h*0.75"
    )


async def _create_segment(
    image_paths: list[str],
    audio_path: str,
    img_duration: float,
    output_path: Path,
    mood: str = "calme",
    *,
    audio_duration: float | None = None,
) -> None:
    """Crée un segment vidéo avec Ken Burns sur les images et une piste audio."""
    from agent.skills.video.ken_burns import apply_ken_burns

    ken_burns_clips: list[Path] = []
    for i, img_path in enumerate(image_paths):
        clip_path = output_path.parent / f"{output_path.stem}_img{i}.mp4"
        pan_dir = (-1) ** i if i > 0 else 0
        await apply_ken_burns(
            Path(img_path), clip_path, duration_s=img_duration, pan_direction=pan_dir
        )
        ken_burns_clips.append(clip_path)

    visual_path = output_path.parent / f"{output_path.stem}_visual.mp4"
    await _concat_clips_with_transitions(
        ken_burns_clips, visual_path, transition_type=_transition_for_mood(mood)
    )

    await _mux_video_with_narration(
        visual_path,
        audio_path,
        output_path,
        audio_duration=audio_duration,
    )


async def _normalize_video_clip(
    clip_path: Path,
    audio_file: "AudioFile | None",
    output_path: Path,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
    strip_source_audio: bool = True,
) -> None:
    """Re-encode a video clip to the pipeline's resolution.

    strip_source_audio=True (default): source audio is replaced by narration or silence.
    strip_source_audio=False: source audio is kept (useful for ambient sound segments).
    """
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    if audio_file and audio_file.local_path:
        await _mux_video_with_narration(
            clip_path,
            audio_file.local_path,
            output_path,
            audio_duration=float(audio_file.duration_s) if audio_file.duration_s else None,
            vf_prefix=vf,
        )
        return
    if not strip_source_audio:
        # Keep source audio as-is (ambient sound, no narration)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "22", "-preset", "fast",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-vf", vf,
            "-c:v", "libx264", "-crf", "22", "-preset", "fast",
            "-c:a", "aac",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            str(output_path),
        ]
    await _run_ffmpeg(cmd)


async def mix_background_music(
    video_path: Path,
    music_path: Path,
    output_path: Path,
    music_volume: float = 0.08,
    duck_narration: bool = False,
) -> None:
    """Mixe une piste musicale en fond sous la narration existante."""
    try:
        probe = ffmpeg.probe(str(video_path))
        duration = float(probe["format"]["duration"])
    except Exception as exc:
        raise RuntimeError(f"Impossible de sonder {video_path} pour le mixage musique: {exc}") from exc
    fade_start = max(0.0, duration - 3.0)

    if duck_narration:
        filter_complex = (
            f"[1:a]volume={music_volume},"
            f"afade=t=out:st={fade_start:.2f}:d=3[music];"
            "[music][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=200:release=1000[ducked];"
            "[0:a][ducked]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    else:
        filter_complex = (
            f"[1:a]volume={music_volume},"
            f"afade=t=out:st={fade_start:.2f}:d=3[music];"
            "[0:a][music]amix=inputs=2:duration=first:normalize=0[aout]"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)
    logger.info("Musique de fond mixée (vol=%.0f%%, duck=%s) → %s", music_volume * 100, duck_narration, output_path)


async def _run_ffmpeg(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode()[-2000:]}")


def _assert_audio_stream(video_path: Path) -> None:
    """Vérifie qu'une piste audio est présente dans le fichier vidéo."""
    try:
        probe = ffmpeg.probe(str(video_path))
    except Exception as exc:
        raise RuntimeError(f"Impossible de sonder {video_path}: {exc}") from exc
    audio_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise RuntimeError(f"Aucune piste audio dans la vidéo assemblée : {video_path}")


async def assert_audio_has_signal(
    video_path: Path,
    min_mean_db: float = -50.0,
    required: bool = True,
) -> None:
    """Vérifie que la piste audio n'est pas numériquement silencieuse."""
    if not required:
        return
    _assert_audio_stream(video_path)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", str(video_path),
        "-af", "volumedetect",
        "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    mean_db = -91.0
    for line in stderr.decode().splitlines():
        if "mean_volume:" in line:
            try:
                mean_db = float(line.split("mean_volume:")[1].strip().split()[0])
            except (IndexError, ValueError):
                continue
            break
    if mean_db < min_mean_db:
        raise RuntimeError(
            f"Piste audio silencieuse dans {video_path.name} "
            f"(niveau moyen {mean_db:.1f} dB) — vérifiez TTS et musique de fond"
        )


async def _create_vertical_segment_beats(
    timeline: list,
    audio_path: str,
    output_path: Path,
) -> None:
    from agent.skills.video.ken_burns import apply_ken_burns_vertical

    clips: list[Path] = []
    for i, entry in enumerate(timeline):
        duration = max(entry.end_s - entry.start_s, 0.5)
        clip_path = output_path.parent / f"{output_path.stem}_beat{i}.mp4"
        pan_dir = (-1) ** i if i > 0 else 0
        await apply_ken_burns_vertical(
            Path(entry.image_path),
            clip_path,
            duration_s=duration,
            pan_direction=pan_dir,
        )
        clip_path = await _apply_beat_text_overlay(clip_path, entry, vertical=True)
        clips.append(clip_path)

    concat_file = output_path.parent / f"{output_path.stem}_beats.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in clips),
        encoding="utf-8",
    )
    visual_path = output_path.parent / f"{output_path.stem}_visual.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c", "copy",
        str(visual_path),
    ]
    await _run_ffmpeg(cmd)
    await _mux_video_with_narration(
        visual_path,
        audio_path,
        output_path,
    )


async def _create_long_segment_beats(
    timeline: list,
    audio_path: str,
    output_path: Path,
    *,
    mood: str = "calme",
) -> None:
    from agent.skills.video.ken_burns import apply_ken_burns

    clips: list[Path] = []
    for i, entry in enumerate(timeline):
        duration = max(entry.end_s - entry.start_s, 0.5)
        clip_path = output_path.parent / f"{output_path.stem}_beat{i}.mp4"
        pan_dir = (-1) ** i if i > 0 else 0
        await apply_ken_burns(
            Path(entry.image_path),
            clip_path,
            duration_s=duration,
            pan_direction=pan_dir,
        )
        clip_path = await _apply_beat_text_overlay(clip_path, entry, vertical=False)
        clips.append(clip_path)

    visual_path = output_path.parent / f"{output_path.stem}_visual.mp4"
    await _concat_clips_with_transitions(
        clips, visual_path, transition_type=_transition_for_mood(mood)
    )
    await _mux_video_with_narration(
        visual_path,
        audio_path,
        output_path,
        preset="medium",
    )
