from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class ClipSegmentMeta(BaseModel):
    start_s: float
    end_s: float
    reason: str = ""


class ClipMetadata(BaseModel):
    motion_score: int | None = None
    useful_duration_s: float | None = None
    static_ratio: float | None = None
    best_segments: list[ClipSegmentMeta] = Field(default_factory=list)
    summary: str = ""


MotionStyle = Literal["static", "zoom_in", "zoom_out", "pan_left", "pan_right"]
OverlayMode = Literal["none", "drawtext", "svg_overlay"]
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
    overlay_mode: OverlayMode = "none"
    overlay_asset_path: str = ""
    strip_source_audio: bool = True


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
