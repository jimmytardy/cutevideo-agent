from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AiImageOutcome = Literal["validated", "forced_best", "api_failed"]


@dataclass
class AiImageResult:
    outcome: AiImageOutcome
    item: dict | None = None
    temp_s3_key: str | None = None


@dataclass
class MediaGap:
    segment_order: int
    reason: str
    attempts: int
    prompt: str

    def to_dict(self) -> dict:
        return {
            "segment_order": self.segment_order,
            "reason": self.reason,
            "attempts": self.attempts,
            "prompt": self.prompt,
        }
