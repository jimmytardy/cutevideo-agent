from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent.core.config import load_agent_config

SubjectType = Literal[
    "species", "person", "event", "concept", "place", "artwork", "general"
]
NicheRisk = Literal["low", "medium", "high"]


class SegmentValidationBrief(BaseModel):
    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    validation_prompt: str = ""
    min_relevance_score: int | None = None


class MediaValidationBrief(BaseModel):
    subject_entity: str = ""
    subject_type: SubjectType = "general"
    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    ambiguity_warnings: list[str] = Field(default_factory=list)
    validation_prompt: str = ""
    min_relevance_score: int = 60
    niche_risk: NicheRisk = "low"
    segments: dict[int, SegmentValidationBrief] = Field(default_factory=dict)

    def segment_brief(self, order: int) -> SegmentValidationBrief:
        if order in self.segments:
            return self.segments[order]
        return SegmentValidationBrief(
            must_include=list(self.must_include),
            must_exclude=list(self.must_exclude),
            validation_prompt=self.validation_prompt,
            min_relevance_score=self.min_relevance_score,
        )

    def min_score_for_segment(self, order: int) -> int:
        seg = self.segment_brief(order)
        if seg.min_relevance_score is not None:
            return seg.min_relevance_score
        return self.min_relevance_score

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> MediaValidationBrief | None:
        if not data or not isinstance(data, dict):
            return None
        segments_raw = data.get("segments", {})
        segments: dict[int, SegmentValidationBrief] = {}
        if isinstance(segments_raw, dict):
            for key, val in segments_raw.items():
                if isinstance(val, dict):
                    segments[int(key)] = SegmentValidationBrief.model_validate(val)
        payload = {k: v for k, v in data.items() if k != "segments"}
        brief = cls.model_validate(payload)
        brief.segments = segments
        return brief


class MediaValidationOverride(BaseModel):
    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    validation_prompt: str | None = None
    min_relevance_score: int | None = None


class ChannelMediaValidationConfig(BaseModel):
    media_validation_template: str = ""
    default_min_relevance_score: int | None = None


def load_media_validation_defaults() -> dict[str, Any]:
    cfg = load_agent_config().get("media_sources", {})
    return {
        "relevance_min_score_default": int(cfg.get("relevance_min_score", 60)),
        "relevance_min_score_high_precision": int(
            cfg.get("relevance_min_score_high_precision", 75)
        ),
        "max_search_iterations": int(cfg.get("max_search_iterations", 3)),
        "min_passing_candidates_multiplier": float(
            cfg.get("min_passing_candidates_multiplier", 1.5)
        ),
        "niche_threshold_candidates": int(cfg.get("niche_threshold_candidates", 2)),
        "enable_post_selection_audit": bool(cfg.get("enable_post_selection_audit", True)),
    }


def _merge_unique_lists(*lists: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        for item in lst:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(item.strip())
    return out


def _parse_override(data: dict[str, Any] | None) -> MediaValidationOverride | None:
    if not data or not isinstance(data, dict):
        return None
    raw = data.get("media_validation_override")
    if not raw or not isinstance(raw, dict):
        return None
    return MediaValidationOverride.model_validate(raw)


def _channel_validation_config(channel_config: dict[str, Any] | None) -> ChannelMediaValidationConfig:
    if not channel_config or not isinstance(channel_config, dict):
        return ChannelMediaValidationConfig()
    raw = channel_config.get("media_validation", {})
    if not isinstance(raw, dict):
        raw = {}
    template = str(
        raw.get("media_validation_template")
        or channel_config.get("media_validation_template")
        or ""
    )
    default_score = raw.get("default_min_relevance_score")
    return ChannelMediaValidationConfig(
        media_validation_template=template,
        default_min_relevance_score=int(default_score) if default_score is not None else None,
    )


def _brief_from_scenario_segments(segments: list[dict[str, Any]] | None) -> MediaValidationBrief | None:
    if not segments:
        return None
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        mv = seg.get("media_validation")
        if isinstance(mv, dict) and mv.get("subject_entity"):
            return MediaValidationBrief.from_dict(mv)
    segment_briefs: dict[int, SegmentValidationBrief] = {}
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        order = int(seg.get("order", 0))
        mv = seg.get("media_validation")
        if isinstance(mv, dict):
            segment_briefs[order] = SegmentValidationBrief.model_validate(mv)
    if not segment_briefs:
        return None
    return MediaValidationBrief(segments=segment_briefs)


def _brief_from_project_config(project_config: dict[str, Any] | None) -> MediaValidationBrief | None:
    if not project_config or not isinstance(project_config, dict):
        return None
    raw = project_config.get("media_validation_brief")
    if isinstance(raw, dict):
        return MediaValidationBrief.from_dict(raw)
    return None


def resolve_validation_brief(
    *,
    channel_config: dict[str, Any] | None = None,
    project_config: dict[str, Any] | None = None,
    scenario_segments: list[dict[str, Any]] | None = None,
    theme_category: str = "default",
) -> MediaValidationBrief:
    """Fusionne défauts config, template chaîne, brief auto et override projet."""
    defaults = load_media_validation_defaults()
    default_score = int(defaults["relevance_min_score_default"])
    high_precision = int(defaults["relevance_min_score_high_precision"])

    channel_mv = _channel_validation_config(channel_config)
    auto_brief = (
        _brief_from_project_config(project_config)
        or _brief_from_scenario_segments(scenario_segments)
        or MediaValidationBrief(min_relevance_score=default_score)
    )

    if channel_mv.default_min_relevance_score is not None:
        auto_brief.min_relevance_score = channel_mv.default_min_relevance_score

    if auto_brief.subject_type == "species" or theme_category in ("nature", "animaux"):
        if auto_brief.min_relevance_score == default_score:
            auto_brief.min_relevance_score = high_precision

    project_override = _parse_override(project_config)
    if project_override:
        auto_brief.must_include = _merge_unique_lists(
            auto_brief.must_include, project_override.must_include
        )
        auto_brief.must_exclude = _merge_unique_lists(
            auto_brief.must_exclude, project_override.must_exclude
        )
        if project_override.validation_prompt:
            extra = project_override.validation_prompt.strip()
            if extra:
                auto_brief.validation_prompt = (
                    f"{auto_brief.validation_prompt}\n{extra}".strip()
                    if auto_brief.validation_prompt
                    else extra
                )
        if project_override.min_relevance_score is not None:
            auto_brief.min_relevance_score = project_override.min_relevance_score

    if channel_mv.media_validation_template.strip():
        template = channel_mv.media_validation_template.strip()
        auto_brief.validation_prompt = (
            f"{auto_brief.validation_prompt}\n{template}".strip()
            if auto_brief.validation_prompt
            else template
        )

    return auto_brief


def attach_brief_to_segments(
    segments: list[dict[str, Any]],
    brief: MediaValidationBrief,
) -> list[dict[str, Any]]:
    """Injecte le brief global et les sous-briefs segmentaires dans chaque segment."""
    global_dict = brief.to_dict()
    segment_keys = {k: v for k, v in global_dict.items() if k != "segments"}
    updated: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            updated.append(seg)
            continue
        order = int(seg.get("order", 0))
        seg_copy = dict(seg)
        seg_brief = brief.segment_brief(order)
        seg_copy["media_validation"] = {
            **segment_keys,
            **seg_brief.model_dump(),
            "segments": {str(k): v.model_dump() for k, v in brief.segments.items()},
        }
        updated.append(seg_copy)
    return updated
