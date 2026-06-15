from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from agent.core.config import load_agent_config
from agent.core.montage_plan import BeatClipPlan, MotionStyle
from agent.skills.video.montage_decisions import (
    clip_duration_s,
    compute_xfade_offset,
    load_transition_config,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoProfile:
    width: int
    height: int
    fps: int


def profile_from_config(is_vertical: bool) -> VideoProfile:
    video_cfg = load_agent_config().get("video", {})
    if is_vertical:
        short = video_cfg.get("short", {})
        return VideoProfile(
            width=int(short.get("width", 1080)),
            height=int(short.get("height", 1920)),
            fps=int(short.get("fps", 30)),
        )
    long_cfg = video_cfg.get("long", {})
    return VideoProfile(
        width=int(long_cfg.get("width", 1920)),
        height=int(long_cfg.get("height", 1080)),
        fps=int(long_cfg.get("fps", 25)),
    )


def _load_ken_burns_config() -> dict[str, float | bool]:
    cfg = load_agent_config().get("video", {}).get("ken_burns", {})
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "zoom_factor": float(cfg.get("zoom_factor", 0.03)),
        "pan_enabled": bool(cfg.get("pan_enabled", False)),
    }


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )


def _build_motion_vf(
    input_label: str,
    output_label: str,
    duration_s: float,
    profile: VideoProfile,
    motion_style: MotionStyle,
) -> str:
    kb = _load_ken_burns_config()
    zoom_factor = float(kb["zoom_factor"]) if kb["enabled"] else 0.0
    n_frames = max(int(duration_s * profile.fps), 1)
    w, h, fps = profile.width, profile.height, profile.fps

    if motion_style == "static" or zoom_factor <= 0:
        return (
            f"[{input_label}]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h},fps={fps}[{output_label}]"
        )

    prescale_w = w * 4
    prescale_h = h * 4

    if motion_style == "zoom_out":
        z = f"(1+{zoom_factor}*(1-on/{n_frames}))"
    else:
        z = f"(1+{zoom_factor}*on/{n_frames})"

    crop_w = f"trunc({prescale_w}/{z}/2)*2"
    crop_h = f"trunc({prescale_h}/{z}/2)*2"

    pan_enabled = motion_style in ("pan_left", "pan_right") or bool(kb["pan_enabled"])
    if motion_style == "pan_left":
        pan_expr = f"-{40}*on/{n_frames}"
    elif motion_style == "pan_right":
        pan_expr = f"{40}*on/{n_frames}"
    elif pan_enabled:
        pan_expr = "0"
    else:
        pan_expr = None

    if pan_expr is not None:
        x_expr = f"trunc(({prescale_w}-({crop_w}))/2+({pan_expr})/2)*2"
    else:
        x_expr = f"trunc(({prescale_w}-({crop_w}))/2/2)*2"
    y_expr = f"trunc(({prescale_h}-({crop_h}))/2/2)*2"

    return (
        f"[{input_label}]scale={prescale_w}:{prescale_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={prescale_w}:{prescale_h},"
        f"crop=w='{crop_w}':h='{crop_h}':x='{x_expr}':y='{y_expr}',"
        f"scale={w}:{h}:flags=lanczos,fps={fps}[{output_label}]"
    )


def _build_video_trim_vf(
    input_label: str,
    output_label: str,
    trim_start: float,
    duration_s: float,
    profile: VideoProfile,
) -> str:
    w, h, fps = profile.width, profile.height, profile.fps
    end = trim_start + duration_s
    return (
        f"[{input_label}]trim=start={trim_start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,"
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}[{output_label}]"
    )


def _build_color_vf(
    input_label: str,
    output_label: str,
    duration_s: float,
    profile: VideoProfile,
) -> str:
    w, h, fps = profile.width, profile.height, profile.fps
    return f"[{input_label}]fps={fps},scale={w}:{h}[{output_label}]"


def _build_drawtext_filter(
    input_label: str,
    output_label: str,
    text: str,
    vertical: bool,
) -> str:
    safe = _escape_drawtext(text[:80])
    y_expr = "h*0.75" if vertical else "h*0.82"
    fontsize = 38 if vertical else 44
    return (
        f"[{input_label}]drawtext=font='DejaVu Sans':text='{safe}':fontsize={fontsize}:"
        f"fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=6:borderw=2:bordercolor=black:"
        f"x=(w-text_w)/2:y={y_expr}[{output_label}]"
    )


def build_segment_filter_complex(
    clips: list[BeatClipPlan],
    profile: VideoProfile,
    *,
    is_vertical: bool,
) -> tuple[list[str], str, str]:
    """Construit les arguments d'entrée FFmpeg et le filter_complex pour un segment."""
    if not clips:
        raise ValueError("Aucun clip dans le segment")

    trans_cfg = load_transition_config()
    trans_dur = trans_cfg.duration_s if trans_cfg.enabled else 0.0
    durations = [clip_duration_s(c) for c in clips]

    input_args: list[str] = []
    filter_parts: list[str] = []
    stream_labels: list[str] = []
    input_idx = 0

    for i, plan in enumerate(clips):
        duration = durations[i]
        processed_label = f"v{i}"

        if plan.asset_type == "color":
            input_args.extend([
                "-f", "lavfi",
                "-i", f"color=c=0x1a1a2e:s={profile.width}x{profile.height}:d={duration:.3f}:r={profile.fps}",
            ])
            filter_parts.append(
                _build_color_vf(f"{input_idx}:v", processed_label, duration, profile)
            )
            input_idx += 1
        elif plan.asset_type == "video":
            trim_start = plan.source_trim_start_s
            input_args.extend(["-i", str(plan.asset_path)])
            filter_parts.append(
                _build_video_trim_vf(
                    f"{input_idx}:v", processed_label, trim_start, duration, profile
                )
            )
            input_idx += 1
        else:
            input_args.extend([
                "-loop", "1",
                "-framerate", str(profile.fps),
                "-t", f"{duration:.3f}",
                "-i", str(plan.asset_path),
            ])
            filter_parts.append(
                _build_motion_vf(
                    f"{input_idx}:v", processed_label, duration, profile, plan.motion_style
                )
            )
            input_idx += 1

        current_label = processed_label

        if plan.overlay_mode == "svg_overlay" and plan.overlay_asset_path:
            overlay_path = Path(plan.overlay_asset_path)
            if overlay_path.exists():
                input_args.extend(["-i", str(overlay_path)])
                overlaid = f"v{i}o"
                filter_parts.append(
                    f"[{current_label}][{input_idx}:v]overlay=0:0:format=auto[{overlaid}]"
                )
                current_label = overlaid
                input_idx += 1
        elif plan.overlay_mode == "drawtext" and plan.on_screen_text:
            draw_label = f"v{i}t"
            filter_parts.append(
                _build_drawtext_filter(
                    current_label, draw_label, plan.on_screen_text, is_vertical
                )
            )
            current_label = draw_label

        stream_labels.append(current_label)

    if len(stream_labels) == 1:
        out_label = "vout"
        filter_parts.append(f"[{stream_labels[0]}]null[{out_label}]")
    elif trans_cfg.enabled and trans_dur > 0:
        current = stream_labels[0]
        for j in range(1, len(stream_labels)):
            next_label = stream_labels[j]
            step_out = f"xf{j}"
            transition = clips[j - 1].transition_out or "fade"
            t_dur = clips[j - 1].transition_duration_s or trans_dur
            offset = compute_xfade_offset(durations, j - 1, t_dur)
            filter_parts.append(
                f"[{current}][{next_label}]xfade=transition={transition}:"
                f"duration={t_dur:.3f}:offset={offset:.3f}[{step_out}]"
            )
            current = step_out
        out_label = "vout"
        filter_parts.append(f"[{current}]null[{out_label}]")
    else:
        concat_in = "".join(f"[{lbl}]" for lbl in stream_labels)
        out_label = "vout"
        filter_parts.append(f"{concat_in}concat=n={len(stream_labels)}:v=1:a=0[{out_label}]")

    return input_args, ";".join(filter_parts), out_label


async def render_segment_from_clips(
    clips: list[BeatClipPlan],
    audio_path: str,
    output_path: Path,
    *,
    is_vertical: bool = False,
) -> None:
    """Encode un segment complet (un seul passage libx264)."""
    profile = profile_from_config(is_vertical)
    input_args, filter_complex, vout = build_segment_filter_complex(
        clips, profile, is_vertical=is_vertical
    )
    audio_input_idx = count_audio_input_index(input_args)

    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", f"[{vout}]",
        "-map", f"{audio_input_idx}:a:0",
        "-c:v", "libx264", "-crf", "22", "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg segment render error: {stderr.decode()[-2000:]}")


def count_audio_input_index(input_args: list[str]) -> int:
    return sum(1 for arg in input_args if arg == "-i")
