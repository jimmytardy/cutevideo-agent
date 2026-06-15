from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResearchSource(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""


class TimelineEntry(BaseModel):
    year: str = ""
    event: str = ""


class ResearchBrief(BaseModel):
    """Brief factuel produit par ResearchAgent avant le scénario."""

    subject_entity: str = ""
    key_facts: list[str] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    visual_anchors: list[str] = Field(default_factory=list)
    common_misconceptions: list[str] = Field(default_factory=list)
    narrative_angles: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    niche_risk: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ResearchBrief | None:
        if not data:
            return None
        try:
            timeline_raw = data.get("timeline") or []
            timeline = [
                TimelineEntry.model_validate(t) if isinstance(t, dict) else TimelineEntry(event=str(t))
                for t in timeline_raw
            ]
            sources_raw = data.get("sources") or []
            sources = [
                ResearchSource.model_validate(s) if isinstance(s, dict) else ResearchSource(title=str(s))
                for s in sources_raw
            ]
            return cls(
                subject_entity=str(data.get("subject_entity", "")),
                key_facts=[str(x) for x in data.get("key_facts", []) if x],
                timeline=timeline,
                sources=sources,
                visual_anchors=[str(x) for x in data.get("visual_anchors", []) if x],
                common_misconceptions=[str(x) for x in data.get("common_misconceptions", []) if x],
                narrative_angles=[str(x) for x in data.get("narrative_angles", []) if x],
                confidence=float(data.get("confidence", 0.0)),
                niche_risk=str(data.get("niche_risk", "medium")),
            )
        except Exception:
            return None
