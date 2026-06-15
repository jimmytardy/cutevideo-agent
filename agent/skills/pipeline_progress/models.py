from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentProgressData:
    done: int
    total: int
    percent: int
    detail: str | None = None
    segments_done: int | None = None
    segments_total: int | None = None


@dataclass(frozen=True)
class PipelineProgressSnapshot:
    preparation: dict[str, AgentProgressData] = field(default_factory=dict)
    iterations: dict[int, dict[str, AgentProgressData]] = field(default_factory=dict)
    post_production: dict[str, AgentProgressData] = field(default_factory=dict)
