from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class ClipSegmentMeta(BaseModel):
    start_s: float
    end_s: float
    reason: str = ""
    score: int = 0
    peak_s: float | None = None


CompositionType = Literal[
    "portrait", "wide", "detail", "crowd", "text_heavy", "abstract"
]


class ClipMetadata(BaseModel):
    motion_score: int | None = None
    useful_duration_s: float | None = None
    static_ratio: float | None = None
    best_segments: list[ClipSegmentMeta] = Field(default_factory=list)
    summary: str = ""
    salient_box: list[float] | None = None
    faces: int = 0
    face_box: list[float] | None = None
    horizon_y: float | None = None
    composition: CompositionType | None = None
    energy: int | None = None
    emotional_tone: str = ""
    dominant_colors: list[str] = Field(default_factory=list)


MotionStyle = Literal["static", "zoom_in", "zoom_out", "pan_left", "pan_right", "punch_zoom"]
OverlayMode = Literal["none", "drawtext", "svg_overlay", "ass_overlay"]
AssetType = Literal["image", "video", "color"]


class BeatClipPlan(BaseModel):
    beat_order: int
    source_beat_orders: list[int] = Field(default_factory=list)
    asset_path: str
    asset_type: AssetType = "image"
    timeline_start_s: float
    timeline_end_s: float
    source_trim_start_s: float = 0.0
    source_trim_end_s: float | None = None
    trim_reason: str = ""
    on_screen_text: str = ""
    text_layout: list[dict[str, Any]] = Field(default_factory=list)
    visual_type: str = "documentary_photo"
    transition_out: str = "fade"
    transition_duration_s: float | None = None
    motion_style: MotionStyle = "zoom_in"
    motion_focus: list[float] | None = None
    crop_box: list[float] | None = None
    overlay_mode: OverlayMode = "none"
    overlay_asset_path: str = ""
    text_animation: str = ""
    strip_source_audio: bool = True
    audio_lead_s: float = 0.0
    audio_trail_s: float = 0.0


class EffectiveBeat(BaseModel):
    order: int
    phrase_anchor: str
    visual_type: str = "documentary_photo"
    on_screen_text: str = ""
    adaptation: Literal["unchanged", "merged", "split", "added", "removed"] = "unchanged"
    source_beat_orders: list[int] = Field(default_factory=list)
    transition_hint: str = ""
    motion_hint: str = ""


class SegmentMontagePlan(BaseModel):
    segment_order: int
    effective_beats: list[EffectiveBeat] = Field(default_factory=list)
    clips: list[BeatClipPlan] = Field(default_factory=list)
    adaptation_notes: str = ""
    segment_mood: str = "calme"
    default_transition: str = "fade"
    music_path: str = ""


class MontagePlanData(BaseModel):
    project_id: uuid.UUID
    iteration: int
    segments: list[SegmentMontagePlan] = Field(default_factory=list)
    planner_notes: str = ""
    scenario_patch: dict[str, Any] | None = None
    is_vertical: bool = False

    def to_db_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_db_dict(cls, data: dict[str, Any]) -> MontagePlanData:
        return cls.model_validate(data)


def collect_clip_cut_times(plan: MontagePlanData) -> list[float]:
    """Horodatages absolus des changements visuels intra-segment (après le 1er clip)."""
    times: list[float] = []
    segment_offset = 0.0
    for seg in sorted(plan.segments, key=lambda s: s.segment_order):
        for idx, clip in enumerate(seg.clips):
            if idx > 0:
                times.append(segment_offset + clip.timeline_start_s)
        if seg.clips:
            segment_offset += seg.clips[-1].timeline_end_s
    return sorted({round(t, 3) for t in times if t > 0.05})
