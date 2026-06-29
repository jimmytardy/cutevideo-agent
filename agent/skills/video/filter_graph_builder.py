from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from agent.core.config import load_agent_config
from agent.core.montage_plan import BeatClipPlan, MotionStyle
from typing import Any

from agent.skills.video.montage_decisions import (
    clip_duration_s,
    compute_xfade_offset,
    load_transition_config,
)
from agent.skills.video.montage_profile import load_ken_burns_config

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


def _load_ken_burns_config(
    *,
    is_short: bool = False,
    channel_raw_config: dict[str, Any] | None = None,
) -> dict[str, float | bool]:
    return load_ken_burns_config(is_short=is_short, channel_raw_config=channel_raw_config)


def color_grade_from_style_block(style_block: str, *, theme: str = "") -> str:
    """P5 — Dérive un étalonnage léger (FFmpeg) du `style_block` de l'art_director.

    Appliqué uniformément à toute la timeline (réel + IA) pour harmoniser le look.
    Retourne une chaîne de filtres FFmpeg (ex. ``colorbalance=...,eq=...,lut3d=...``)
    ou ``""`` si le style ne suggère aucune dominante (rendu neutre).
    """
    from agent.skills.video.video_style_config import resolve_lut_path

    s = (style_block or "").lower()
    parts: list[str] = []

    lut_path = resolve_lut_path(theme)
    if lut_path is not None:
        lut_escaped = str(lut_path.resolve()).replace("\\", "/").replace(":", "\\:")
        parts.append(f"lut3d=file='{lut_escaped}'")

    if not s.strip() and parts:
        return ",".join(parts)

    if not s.strip():
        return ""

    warm_kw = ("warm", "sepia", "amber", "ambr", "golden", "earthy", "chaud")
    cool_kw = ("cool", " blue", "teal", "cold", "cosmic", "froid", "noir")
    if any(k in s for k in warm_kw):
        parts.append("colorbalance=rm=0.05:gm=0.02:bm=-0.05")
    elif any(k in s for k in cool_kw):
        parts.append("colorbalance=rm=-0.04:bm=0.06")

    desat_kw = ("desaturated", "muted", "low-key", "low key", "noir", "désatur")
    vivid_kw = ("vivid", "saturated", "rich", "vibrant", "bold")
    if any(k in s for k in desat_kw):
        parts.append("eq=saturation=0.85:contrast=1.06")
    elif any(k in s for k in vivid_kw):
        parts.append("eq=saturation=1.12:contrast=1.04")
    else:
        parts.append("eq=saturation=1.05:contrast=1.03")

    return ",".join(parts)


def build_source_pregrade_vf(visual_type: str) -> str:
    """Pré-grade léger pour unifier archives / sources hétérogènes."""
    vt = (visual_type or "").lower()
    if vt == "archival_footage":
        return "eq=saturation=0.88:contrast=1.05,noise=alls=6:allf=t+u"
    if vt in ("crime_documentary", "news_broll"):
        return "eq=saturation=0.92:contrast=1.04"
    return ""


def build_texture_vf(
    *,
    theme: str = "",
    clip_index: int = 0,
) -> str:
    """Chaîne de filtres texture (grain, vignette, light leak, VHS) post-grade."""
    from agent.skills.video.video_style_config import load_texture_config

    cfg = load_texture_config(theme=theme)
    parts: list[str] = []

    if cfg.grain > 0:
        parts.append(f"noise=alls={cfg.grain}:allf=t+u")
    if cfg.vignette:
        parts.append(f"vignette=angle={cfg.vignette_angle}")
    if cfg.light_leak and clip_index % 3 == 0:
        opacity = max(min(cfg.light_leak_opacity, 0.5), 0.05)
        parts.append(
            f"geq="
            f"r='r(X,Y)+{opacity:.2f}*255*lte(X,W*0.15)*gte(Y,H*0.1)':"
            f"g='g(X,Y)+{opacity * 0.6:.2f}*255*lte(X,W*0.15)*gte(Y,H*0.1)':"
            f"b='b(X,Y)'"
        )
    if cfg.vhs:
        shift = max(cfg.vhs_shift, 1)
        parts.append(
            f"rgbashift=rh={shift}:gh=-{shift}:bh=0,"
            f"geq=lum='if(mod(floor(Y/2),2),lum(X,Y)*0.92,lum(X,Y))'"
        )
    return ",".join(parts)


def _map_xfade_transition(name: str) -> str:
    if name == "flash_impact":
        return "fadewhite"
    if name == "glitch":
        return "fade"
    return name


def _build_transition_filter(
    current: str,
    next_label: str,
    step_out: str,
    transition: str,
    t_dur: float,
    offset: float,
    profile: VideoProfile,
) -> str:
    """Assemble une transition xfade ou glitch hors-xfade."""
    from agent.skills.video.video_style_config import load_impact_transition_config

    if transition == "glitch":
        impact = load_impact_transition_config()
        glitch_s = impact.glitch_frames / max(profile.fps, 1)
        end = offset + glitch_s
        raw = f"{step_out}_raw"
        return (
            f"[{current}][{next_label}]xfade=transition=fade:duration=0.04:offset={offset:.3f}[{raw}];"
            f"[{raw}]rgbashift=rh=5:gh=-5:bh=2:enable='between(t,{offset:.3f},{end:.3f})',"
            f"noise=alls={impact.glitch_noise}:allf=t+u:enable='between(t,{offset:.3f},{end:.3f})'"
            f"[{step_out}]"
        )

    xfade_name = _map_xfade_transition(transition)
    if transition == "flash_impact":
        impact = load_impact_transition_config()
        t_dur = min(t_dur, impact.flash_duration_s)
    return (
        f"[{current}][{next_label}]xfade=transition={xfade_name}:"
        f"duration={t_dur:.3f}:offset={offset:.3f}[{step_out}]"
    )


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )


def _focus_crop_exprs(motion_focus: list[float] | None) -> tuple[str, str]:
    if not motion_focus:
        return "(in_w-out_w)/2", "(in_h-out_h)/2"
    if len(motion_focus) >= 4:
        fcx = f"({motion_focus[0]}+{motion_focus[2]}/2)"
        fcy = f"({motion_focus[1]}+{motion_focus[3]}/2)"
    else:
        fcx, fcy = str(motion_focus[0]), str(motion_focus[1])
    x_expr = f"max(0\\,min({fcx}*in_w-out_w/2\\,in_w-out_w))"
    y_expr = f"max(0\\,min({fcy}*in_h-out_h/2\\,in_h-out_h))"
    return x_expr, y_expr


def _aspect_aware_crop_exprs(
    crop_box: list[float] | None,
    target_w: int,
    target_h: int,
) -> tuple[str, str]:
    center_x, center_y = "(in_w-out_w)/2", "(in_h-out_h)/2"
    if not crop_box:
        return center_x, center_y
    salient_x, salient_y = _focus_crop_exprs(crop_box)
    target_ar = target_w / target_h
    x_expr = f"if(gt(abs(in_w/in_h-{target_ar:.8f})\\,0.01)\\,{salient_x}\\,{center_x})"
    y_expr = f"if(gt(abs(in_w/in_h-{target_ar:.8f})\\,0.01)\\,{salient_y}\\,{center_y})"
    return x_expr, y_expr


def _build_motion_vf(
    input_label: str,
    output_label: str,
    duration_s: float,
    profile: VideoProfile,
    motion_style: MotionStyle,
    *,
    is_short: bool = False,
    motion_focus: list[float] | None = None,
    crop_box: list[float] | None = None,
    channel_raw_config: dict[str, Any] | None = None,
) -> str:
    kb = _load_ken_burns_config(is_short=is_short, channel_raw_config=channel_raw_config)
    zoom_factor = float(kb["zoom_factor"]) if kb["enabled"] else 0.0
    n_frames = max(int(duration_s * profile.fps), 1)
    w, h, fps = profile.width, profile.height, profile.fps

    if motion_style == "static" or zoom_factor <= 0:
        if crop_box:
            x_expr, y_expr = _aspect_aware_crop_exprs(crop_box, w, h)
            return (
                f"[{input_label}]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={w}:{h}:x='{x_expr}':y='{y_expr}',fps={fps}[{output_label}]"
            )
        return (
            f"[{input_label}]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h},fps={fps}[{output_label}]"
        )

    prescale_w = (w * 3 // 2) // 2 * 2
    prescale_h = (h * 3 // 2) // 2 * 2

    if motion_style == "punch_zoom":
        punch_frames = max(1, min(int(0.3 * fps), n_frames))
        z = f"if(lt(n\\,{punch_frames})\\,1+0.08*n/{punch_frames}\\,1.08)"
    elif motion_style == "zoom_out":
        z = f"(1+{zoom_factor}*(1-n/{n_frames}))"
    else:
        z = f"(1+{zoom_factor}*n/{n_frames})"

    scale_w = f"trunc(iw*{z}/2)*2"
    scale_h = f"trunc(ih*{z}/2)*2"

    pan_enabled = motion_style in ("pan_left", "pan_right") or bool(kb["pan_enabled"])
    if motion_style == "pan_left":
        pan_expr = f"-{40}*n/{n_frames}"
    elif motion_style == "pan_right":
        pan_expr = f"{40}*n/{n_frames}"
    elif pan_enabled:
        pan_expr = "0"
    else:
        pan_expr = None

    if pan_expr is not None:
        base_x, y_expr = _focus_crop_exprs(motion_focus)
        x_expr = f"{base_x}+({pan_expr})"
    else:
        x_expr, y_expr = _focus_crop_exprs(motion_focus)

    return (
        f"[{input_label}]scale={prescale_w}:{prescale_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={prescale_w}:{prescale_h},"
        f"scale=w='{scale_w}':h='{scale_h}':eval=frame:flags=lanczos,"
        f"crop={prescale_w}:{prescale_h}:x='{x_expr}':y='{y_expr}',"
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
    *,
    visual_type: str = "",
    clip_duration_s: float = 0.0,
    beat_index: int = 0,
) -> str:
    safe = _escape_drawtext(text[:80])
    base_y = "h*0.75" if vertical else "h*0.82"
    fontsize = 38 if vertical else 44
    vt = (visual_type or "").lower()
    duration = max(clip_duration_s, 0.5)

    if beat_index == 0 and vertical:
        y_expr = f"if(lt(t\\,0.25)\\,{base_y}+(h-{base_y})*(1-t/0.25)\\,{base_y})"
        fade = "alpha='if(lt(t,0.2),t/0.2,1)'"
    elif vt == "statistic_highlight":
        y_expr = base_y
        pulse_frames = min(0.15, duration)
        fade = f"alpha='if(lt(t,{pulse_frames:.2f}),0.5+0.5*sin(PI*t/{pulse_frames:.2f}),1)'"
    else:
        y_expr = base_y
        fade = "alpha='if(lt(t,0.15),t/0.15,1)'"

    return (
        f"[{input_label}]drawtext=font='DejaVu Sans':text='{safe}':fontsize={fontsize}:"
        f"fontcolor=white:{fade}:box=1:boxcolor=black@0.65:boxborderw=6:borderw=2:bordercolor=black:"
        f"x=(w-text_w)/2:y={y_expr}[{output_label}]"
    )


def build_segment_filter_complex(
    clips: list[BeatClipPlan],
    profile: VideoProfile,
    *,
    is_vertical: bool,
    is_short: bool = False,
    narration_audio_path: str | None = None,
    grade: str = "",
    theme: str = "",
    channel_raw_config: dict[str, Any] | None = None,
) -> tuple[list[str], str, str, str]:
    """Construit les arguments d'entrée FFmpeg et le filter_complex pour un segment.

    ``grade`` : chaîne de filtres d'étalonnage appliquée à la sortie vidéo finale
    (voir :func:`color_grade_from_style_block`).
    """
    if not clips:
        raise ValueError("Aucun clip dans le segment")

    trans_cfg = load_transition_config(is_short=is_short, channel_raw_config=channel_raw_config)
    trans_dur = trans_cfg.duration_s if trans_cfg.enabled else 0.0
    durations = [clip_duration_s(c) for c in clips]

    input_args: list[str] = []
    filter_parts: list[str] = []
    stream_labels: list[str] = []
    input_idx = 0
    ambient_audio_specs: list[tuple[int, float, float, float]] = []

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
            if not plan.strip_source_audio:
                ambient_audio_specs.append(
                    (input_idx, trim_start, duration, plan.timeline_start_s)
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
                    f"{input_idx}:v", processed_label, duration, profile, plan.motion_style,
                    is_short=is_short,
                    motion_focus=plan.motion_focus,
                    crop_box=plan.crop_box,
                    channel_raw_config=channel_raw_config,
                )
            )
            input_idx += 1

        pregrade = build_source_pregrade_vf(plan.visual_type)
        if pregrade:
            graded_clip = f"{processed_label}pg"
            filter_parts.append(f"[{processed_label}]{pregrade}[{graded_clip}]")
            processed_label = graded_clip

        current_label = processed_label

        if plan.overlay_mode == "svg_overlay" and plan.overlay_asset_path:
            overlay_path = Path(plan.overlay_asset_path)
            if overlay_path.exists():
                input_args.extend(["-i", str(overlay_path)])
                overlaid = f"v{i}o"
                filter_parts.append(
                    f"[{input_idx}:v]format=rgba,fade=t=in:st=0:d=0.15:alpha=1[ov{i}f];"
                    f"[{current_label}][ov{i}f]overlay=0:0:format=auto[{overlaid}]"
                )
                current_label = overlaid
                input_idx += 1
        elif plan.overlay_mode == "drawtext" and plan.on_screen_text:
            draw_label = f"v{i}t"
            filter_parts.append(
                _build_drawtext_filter(
                    current_label,
                    draw_label,
                    plan.on_screen_text,
                    is_vertical,
                    visual_type=plan.visual_type,
                    clip_duration_s=duration,
                    beat_index=i,
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
            if transition == "flash_impact":
                from agent.skills.video.video_style_config import load_impact_transition_config

                t_dur = min(t_dur, load_impact_transition_config().flash_duration_s)
            offset = compute_xfade_offset(durations, j - 1, t_dur)
            filter_parts.append(
                _build_transition_filter(
                    current, next_label, step_out, transition, t_dur, offset, profile
                )
            )
            current = step_out
        out_label = "vout"
        filter_parts.append(f"[{current}]null[{out_label}]")
    else:
        concat_in = "".join(f"[{lbl}]" for lbl in stream_labels)
        out_label = "vout"
        filter_parts.append(f"{concat_in}concat=n={len(stream_labels)}:v=1:a=0[{out_label}]")

    if grade.strip():
        graded = "vgr"
        filter_parts.append(f"[{out_label}]{grade.strip()}[{graded}]")
        out_label = graded

    texture = build_texture_vf(theme=theme, clip_index=0)
    if texture.strip():
        textured = "vtx"
        filter_parts.append(f"[{out_label}]{texture.strip()}[{textured}]")
        out_label = textured

    if not narration_audio_path:
        return input_args, ";".join(filter_parts), out_label, "aout"

    narration_idx = input_idx
    input_args.extend(["-i", narration_audio_path])
    narration_duration_s = max(
        (c.timeline_end_s + c.audio_trail_s for c in clips),
        default=0.0,
    )
    narr_filters, narr_label = _build_narration_audio_filters(
        narration_idx,
        clips,
        narration_duration_s=narration_duration_s,
    )
    filter_parts.extend(narr_filters)

    ambient_volume = 0.35
    ambient_labels: list[str] = []
    for spec_i, (vid_idx, trim_start, dur, delay_s) in enumerate(ambient_audio_specs):
        amb_label = f"amb{spec_i}"
        end = trim_start + dur
        delay_ms = max(int(delay_s * 1000), 0)
        filter_parts.append(
            f"[{vid_idx}:a]atrim=start={trim_start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,"
            f"volume={ambient_volume},adelay={delay_ms}|{delay_ms}[{amb_label}]"
        )
        ambient_labels.append(amb_label)

    if ambient_labels:
        if len(ambient_labels) == 1:
            mixed_amb = ambient_labels[0]
        else:
            mixed_amb = "ambmix"
            ins = "".join(f"[{lbl}]" for lbl in ambient_labels)
            filter_parts.append(
                f"{ins}amix=inputs={len(ambient_labels)}:duration=longest:normalize=0[{mixed_amb}]"
            )
        filter_parts.append(
            f"[{narr_label}][{mixed_amb}]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    else:
        filter_parts.append(f"[{narr_label}]anull[aout]")

    return input_args, ";".join(filter_parts), out_label, "aout"


def _build_narration_audio_filters(
    narration_idx: int,
    clips: list[BeatClipPlan],
    *,
    narration_duration_s: float,
) -> tuple[list[str], str]:
    """Découpe la narration par clip avec décalages J/L."""
    has_jl = any(c.audio_lead_s > 0 or c.audio_trail_s > 0 for c in clips)
    if not has_jl:
        return [f"[{narration_idx}:a]anull[narrout]"], "narrout"

    filter_parts: list[str] = []
    slice_labels: list[str] = []
    for i, clip in enumerate(clips):
        trim_start = max(0.0, clip.timeline_start_s - clip.audio_lead_s)
        trim_end = min(narration_duration_s, clip.timeline_end_s + clip.audio_trail_s)
        if trim_end <= trim_start + 0.01:
            continue
        output_offset = max(0.0, clip.timeline_start_s - clip.audio_lead_s)
        delay_ms = int(output_offset * 1000)
        label = f"narr{i}"
        slice_dur = trim_end - trim_start
        parts = [
            f"atrim=start={trim_start:.3f}:end={trim_end:.3f}",
            "asetpts=PTS-STARTPTS",
            "afade=t=in:st=0:d=0.02",
        ]
        if slice_dur > 0.05:
            parts.append(f"afade=t=out:st={max(0.0, slice_dur - 0.02):.3f}:d=0.02")
        parts.append(f"adelay={delay_ms}|{delay_ms}")
        filter_parts.append(f"[{narration_idx}:a]{','.join(parts)}[{label}]")
        slice_labels.append(label)

    if not slice_labels:
        return [f"[{narration_idx}:a]anull[narrout]"], "narrout"
    if len(slice_labels) == 1:
        return filter_parts, slice_labels[0]
    mixed = "narrmix"
    ins = "".join(f"[{lbl}]" for lbl in slice_labels)
    filter_parts.append(
        f"{ins}amix=inputs={len(slice_labels)}:duration=longest:normalize=0[{mixed}]"
    )
    return filter_parts, mixed


async def render_segment_from_clips(
    clips: list[BeatClipPlan],
    audio_path: str,
    output_path: Path,
    *,
    is_vertical: bool = False,
    grade: str = "",
    theme: str = "",
    channel_raw_config: dict[str, Any] | None = None,
) -> None:
    """Encode un segment complet (un seul passage libx264)."""
    profile = profile_from_config(is_vertical)
    audio_duration_s = await _probe_audio_duration(audio_path)
    input_args, filter_complex, vout, aout = build_segment_filter_complex(
        clips,
        profile,
        is_vertical=is_vertical,
        is_short=is_vertical,
        narration_audio_path=audio_path,
        grade=grade,
        theme=theme,
        channel_raw_config=channel_raw_config,
    )

    from agent.skills.video.ffmpeg_runtime import (
        ffmpeg_preset,
        filter_thread_args,
        run_ffmpeg,
        thread_args,
    )

    cmd = [
        "ffmpeg", "-y",
        *filter_thread_args(),
        *input_args,
        "-filter_complex", filter_complex,
        "-map", f"[{vout}]",
        "-map", f"[{aout}]",
        *thread_args(),
        "-c:v", "libx264", "-crf", "22", "-preset", ffmpeg_preset(),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{audio_duration_s:.3f}",
        str(output_path),
    ]

    await run_ffmpeg(cmd, error_prefix="FFmpeg segment render error")


async def _probe_audio_duration(audio_path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return max(float(stdout.decode().strip() or "0"), 0.5)


def count_audio_input_index(input_args: list[str]) -> int:
    return sum(1 for arg in input_args if arg == "-i")
