from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

"""P1/P4 — Design sonore : effets ponctuels synthétisés (whoosh, pop, impact, riser)."""

_REVEAL_HOOKS: frozenset[str] = frozenset({"fait_surprenant", "revelateur", "révélateur", "chiffre"})

_WHOOSH_GAIN_DB_VOICE = -22.0
_WHOOSH_GAIN_DB_NO_VOICE = -16.0
_ACCENT_GAIN_DB_VOICE = -20.0
_ACCENT_GAIN_DB_NO_VOICE = -14.0
_WHOOSH_GAIN_DB_BEAT_CUT = -26.0

_SFX_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "sfx" / "manifest.json"


@dataclass(frozen=True)
class SfxCue:
    time_s: float
    kind: str  # whoosh | accent | pop | impact | riser | click
    gain_db: float


def _palette() -> dict[str, tuple[float, float]]:
    from agent.skills.video.video_style_config import load_sfx_palette

    cfg = load_sfx_palette()
    return {kind: (item.gain_db, item.duration_s) for kind, item in cfg.items()}


def build_sfx_cues(
    segment_meta: dict[int, dict],
    *,
    max_cues: int = 24,
) -> list[SfxCue]:
    if not segment_meta:
        return []

    ordered = sorted(segment_meta.items())
    has_narration = any(m.get("needs_voice") for m in segment_meta.values())
    palette = _palette()
    whoosh_gain = _WHOOSH_GAIN_DB_VOICE if has_narration else _WHOOSH_GAIN_DB_NO_VOICE
    accent_gain = palette.get("accent", (_ACCENT_GAIN_DB_VOICE, 0.6))[0]
    if has_narration:
        accent_gain = min(accent_gain, _ACCENT_GAIN_DB_VOICE)
    riser_gain = palette.get("riser", (-20.0, 1.5))[0]

    cues: list[SfxCue] = []
    start = 0.0
    for idx, (_order, meta) in enumerate(ordered):
        if idx > 0:
            cues.append(SfxCue(time_s=max(start - 0.35, 0.0), kind="riser", gain_db=riser_gain))
            cues.append(SfxCue(time_s=max(start - 0.15, 0.0), kind="whoosh", gain_db=whoosh_gain))
        hook = str(meta.get("hook_type") or "").strip().lower()
        if hook in _REVEAL_HOOKS:
            impact_gain = palette.get("impact", (-16.0, 0.4))[0]
            cues.append(SfxCue(time_s=start + 0.05, kind="impact", gain_db=impact_gain))
            cues.append(SfxCue(time_s=start + 0.05, kind="accent", gain_db=accent_gain))
        start += float(meta.get("duration_s", 30) or 0)

    cues.sort(key=lambda c: c.time_s)
    return cues[:max_cues]


def build_overlay_cues(
    plan: object,
    *,
    has_narration: bool = True,
    max_cues: int = 24,
) -> list[SfxCue]:
    """Place pop/impact sur apparitions de texte et stats du montage plan."""
    from agent.core.montage_plan import MontagePlanData

    if isinstance(plan, MontagePlanData):
        plan_data = plan
    else:
        plan_data = MontagePlanData.from_db_dict(plan)  # type: ignore[arg-type]

    palette = _palette()
    pop_gain = palette.get("pop", (-18.0, 0.2))[0]
    impact_gain = palette.get("impact", (-16.0, 0.4))[0]
    if has_narration:
        pop_gain = min(pop_gain, -18.0)
        impact_gain = min(impact_gain, -16.0)

    cues: list[SfxCue] = []
    segment_offset = 0.0
    for seg in sorted(plan_data.segments, key=lambda s: s.segment_order):
        for clip in seg.clips:
            t = segment_offset + clip.timeline_start_s
            has_text = bool(clip.on_screen_text.strip()) and clip.overlay_mode in (
                "drawtext",
                "ass_overlay",
                "svg_overlay",
            )
            if has_text:
                cues.append(SfxCue(time_s=t, kind="pop", gain_db=pop_gain))
            if (clip.visual_type or "").lower() == "statistic_highlight":
                cues.append(SfxCue(time_s=t + 0.05, kind="impact", gain_db=impact_gain))
        if seg.clips:
            segment_offset += seg.clips[-1].timeline_end_s

    cues.sort(key=lambda c: c.time_s)
    return cues[:max_cues]


_CLICK_TRANSITIONS = frozenset({"circleopen", "pixelize"})


def build_transition_cues(
    plan: object,
    *,
    has_narration: bool = True,
    max_cues: int = 24,
) -> list[SfxCue]:
    """Click SFX sur transitions circleopen / pixelize."""
    from agent.core.montage_plan import MontagePlanData

    if isinstance(plan, MontagePlanData):
        plan_data = plan
    else:
        plan_data = MontagePlanData.from_db_dict(plan)  # type: ignore[arg-type]

    palette = _palette()
    click_gain = palette.get("click", (-22.0, 0.08))[0]
    if has_narration:
        click_gain = min(click_gain, -22.0)

    cues: list[SfxCue] = []
    segment_offset = 0.0
    for seg in sorted(plan_data.segments, key=lambda s: s.segment_order):
        for idx, clip in enumerate(seg.clips):
            if idx >= len(seg.clips) - 1:
                continue
            transition = (clip.transition_out or "").lower()
            if transition not in _CLICK_TRANSITIONS:
                continue
            t = segment_offset + clip.timeline_end_s - float(clip.transition_duration_s or 0)
            cues.append(SfxCue(time_s=max(t, 0.0), kind="click", gain_db=click_gain))
        if seg.clips:
            segment_offset += seg.clips[-1].timeline_end_s

    cues.sort(key=lambda c: c.time_s)
    return cues[:max_cues]


def build_motion_cues(
    plan: object,
    *,
    has_narration: bool = True,
    max_cues: int = 24,
) -> list[SfxCue]:
    """Impact à t=0 des clips punch_zoom."""
    from agent.core.montage_plan import MontagePlanData

    if isinstance(plan, MontagePlanData):
        plan_data = plan
    else:
        plan_data = MontagePlanData.from_db_dict(plan)  # type: ignore[arg-type]

    palette = _palette()
    impact_gain = palette.get("impact", (-16.0, 0.4))[0]
    if has_narration:
        impact_gain = min(impact_gain, -16.0)

    cues: list[SfxCue] = []
    segment_offset = 0.0
    for seg in sorted(plan_data.segments, key=lambda s: s.segment_order):
        for clip in seg.clips:
            if (clip.motion_style or "") != "punch_zoom":
                continue
            t = segment_offset + clip.timeline_start_s
            cues.append(SfxCue(time_s=t + 0.05, kind="impact", gain_db=impact_gain))
        if seg.clips:
            segment_offset += seg.clips[-1].timeline_end_s

    cues.sort(key=lambda c: c.time_s)
    return cues[:max_cues]


def collect_reveal_timestamps(
    segment_meta: dict[int, dict],
    overlay_cues: list[SfxCue] | None = None,
) -> list[float]:
    """Timestamps pour coupure musicale sur révélation."""
    times: list[float] = []
    start = 0.0
    for _order, meta in sorted(segment_meta.items()):
        hook = str(meta.get("hook_type") or "").strip().lower()
        if hook in _REVEAL_HOOKS:
            times.append(start + 0.05)
        start += float(meta.get("duration_s", 30) or 0)

    if overlay_cues:
        for cue in overlay_cues:
            if cue.kind in ("impact", "accent"):
                times.append(cue.time_s)

    return sorted({round(t, 3) for t in times if t >= 0})


def build_beat_cut_cues(
    clip_starts: list[float],
    *,
    max_per_minute: int = 12,
    video_duration_s: float | None = None,
) -> list[SfxCue]:
    if not clip_starts:
        return []

    deduped: list[float] = []
    for t in sorted(clip_starts):
        if deduped and t - deduped[-1] < 0.3:
            continue
        deduped.append(t)

    if video_duration_s and video_duration_s > 0:
        cap = max(1, int(max_per_minute * video_duration_s / 60.0))
        deduped = deduped[:cap]

    return [
        SfxCue(time_s=max(t - 0.08, 0.0), kind="whoosh", gain_db=_WHOOSH_GAIN_DB_BEAT_CUT)
        for t in deduped
    ]


def merge_sfx_cues(*cue_lists: list[SfxCue], max_cues: int = 36) -> list[SfxCue]:
    merged: list[SfxCue] = []
    for cues in cue_lists:
        merged.extend(cues)
    merged.sort(key=lambda c: c.time_s)
    out: list[SfxCue] = []
    for cue in merged:
        if out and abs(cue.time_s - out[-1].time_s) < 0.15 and cue.kind == out[-1].kind:
            continue
        out.append(cue)
    return out[:max_cues]


def _resolve_sfx_file(kind: str) -> Path | None:
    if not _SFX_MANIFEST_PATH.exists():
        return None
    try:
        import json

        manifest = json.loads(_SFX_MANIFEST_PATH.read_text(encoding="utf-8"))
        rel = (manifest.get(kind) or {}).get("path")
        if not rel:
            return None
        path = _SFX_MANIFEST_PATH.parent / str(rel)
        return path if path.exists() else None
    except (OSError, ValueError, TypeError):
        return None


def _synth_input(kind: str) -> tuple[str, float]:
    palette = _palette()
    gain_db, duration_s = palette.get(kind, (-20.0, 0.5))
    file_path = _resolve_sfx_file(kind)
    if file_path is not None:
        return (str(file_path), duration_s)
    if kind == "accent":
        return (f"sine=frequency=784:duration={duration_s}:sample_rate=48000", duration_s)
    if kind == "pop":
        return (
            f"sine=frequency=880:duration={duration_s}:sample_rate=48000",
            duration_s,
        )
    if kind == "impact":
        return (
            f"sine=frequency=55:duration={duration_s}:sample_rate=48000",
            duration_s,
        )
    if kind == "click":
        return (
            f"sine=frequency=1200:duration={duration_s}:sample_rate=48000",
            duration_s,
        )
    if kind == "riser":
        return (
            f"anoisesrc=d={duration_s}:c=pink:r=48000:a=0.7",
            duration_s,
        )
    return (f"anoisesrc=d={duration_s}:c=pink:r=48000:a=0.9", duration_s)


def _shape_filter(kind: str, gain_db: float, delay_ms: int) -> str:
    palette = _palette()
    _, duration_s = palette.get(kind, (-20.0, 0.5))
    if kind == "accent":
        body = f"afade=t=out:st=0.05:d={max(duration_s - 0.05, 0.05):.2f}"
    elif kind == "pop":
        body = (
            f"highpass=f=400,lowpass=f=4000,"
            f"afade=t=in:st=0:d=0.02,afade=t=out:st={max(duration_s - 0.04, 0.02):.2f}:d=0.04"
        )
    elif kind == "impact":
        body = (
            f"lowpass=f=120,"
            f"afade=t=in:st=0:d=0.01,afade=t=out:st={max(duration_s - 0.08, 0.02):.2f}:d=0.08"
        )
    elif kind == "click":
        body = (
            f"highpass=f=800,lowpass=f=6000,"
            f"afade=t=in:st=0:d=0.01,afade=t=out:st={max(duration_s - 0.03, 0.01):.2f}:d=0.03"
        )
    elif kind == "riser":
        body = (
            f"highpass=f=200:enable='between(t,0,{duration_s})',"
            f"volume=enable='between(t,0,{duration_s})':volume='0.3+0.7*t/{duration_s}',"
            f"afade=t=out:st={max(duration_s - 0.2, 0.05):.2f}:d=0.2"
        )
    else:
        body = (
            f"highpass=f=200,lowpass=f=5000,"
            f"afade=t=in:st=0:d=0.1,afade=t=out:st=0.3:d={max(duration_s - 0.3, 0.05):.2f}"
        )
    return f"{body},aformat=channel_layouts=stereo,volume={gain_db}dB,adelay={delay_ms}|{delay_ms}"


def build_sfx_ffmpeg_command(
    video_path: Path,
    cues: list[SfxCue],
    output_path: Path,
) -> list[str]:
    cmd: list[str] = ["ffmpeg", "-y", "-i", str(video_path)]
    for cue in cues:
        source, dur = _synth_input(cue.kind)
        if Path(source).exists():
            cmd += ["-t", f"{dur:.3f}", "-i", source]
        else:
            cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", source]

    filter_parts: list[str] = []
    sfx_labels: list[str] = []
    for i, cue in enumerate(cues, start=1):
        label = f"sfx{i}"
        delay_ms = max(int(cue.time_s * 1000), 0)
        filter_parts.append(f"[{i}:a]{_shape_filter(cue.kind, cue.gain_db, delay_ms)}[{label}]")
        sfx_labels.append(f"[{label}]")

    mix_inputs = "[0:a]" + "".join(sfx_labels)
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(sfx_labels) + 1}:duration=first:normalize=0[aout]"
    )
    from agent.skills.video.ffmpeg_runtime import thread_args

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "0:v", "-map", "[aout]",
        *thread_args(),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(output_path),
    ]
    return cmd


async def apply_sfx_cues(
    video_path: Path,
    cues: list[SfxCue],
    output_path: Path,
) -> Path | None:
    if not cues:
        return None
    from agent.skills.video.ffmpeg_runtime import run_ffmpeg

    cmd = build_sfx_ffmpeg_command(video_path, cues, output_path)
    try:
        await run_ffmpeg(cmd, error_prefix="SFX FFmpeg error")
    except RuntimeError as exc:
        logger.warning("%s", exc)
        return None
    return output_path


def build_ambient_bed_filter(
    *,
    theme: str,
    duration_s: float,
    gain_db: float,
) -> tuple[str, str]:
    """Retourne (lavfi_source, filter_chain) pour un bed d'ambiance synthétique."""
    preset = (theme or "default").lower()
    if preset in ("nature", "wind"):
        source = f"anoisesrc=d={duration_s:.3f}:c=pink:r=48000:a=0.25"
        body = "highpass=f=180,lowpass=f=800,afade=t=in:st=0:d=1.5,afade=t=out:st=0:d=1.5"
    elif preset in ("sport", "crowd", "entertainment"):
        source = f"anoisesrc=d={duration_s:.3f}:c=pink:r=48000:a=0.35"
        body = "highpass=f=300,lowpass=f=2500,afade=t=in:st=0:d=1.0,afade=t=out:st=0:d=1.0"
    else:
        source = f"anoisesrc=d={duration_s:.3f}:c=brown:r=48000:a=0.2"
        body = "highpass=f=120,lowpass=f=600,afade=t=in:st=0:d=2.0,afade=t=out:st=0:d=2.0"
    return source, f"{body},aformat=channel_layouts=stereo,volume={gain_db}dB"


async def apply_ambient_bed(
    video_path: Path,
    output_path: Path,
    *,
    theme: str,
    duration_s: float,
    channel_raw_config: dict | None = None,
) -> Path | None:
    from agent.skills.video.video_style_config import load_ambient_bed_config
    from agent.skills.video.ffmpeg_runtime import run_ffmpeg, thread_args

    cfg = load_ambient_bed_config(channel_raw_config=channel_raw_config)
    if not cfg.get("enabled"):
        return None

    presets = cfg.get("theme_presets", {})
    preset = presets.get((theme or "").lower(), "room")
    gain_db = float(cfg.get("gain_db", -30.0))
    source, bed_filter = build_ambient_bed_filter(
        theme=str(preset),
        duration_s=duration_s,
        gain_db=gain_db,
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-f", "lavfi", "-t", f"{duration_s:.3f}", "-i", source,
        "-filter_complex",
        f"[1:a]{bed_filter}[bed];[0:a][bed]amix=inputs=2:duration=first:normalize=0[aout]",
        "-map", "0:v", "-map", "[aout]",
        *thread_args(),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(output_path),
    ]
    try:
        await run_ffmpeg(cmd, error_prefix="Ambient bed FFmpeg error")
    except RuntimeError as exc:
        logger.warning("%s", exc)
        return None
    return output_path
