from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ImageGenerationRequest:
    prompt: str
    output_dir: Path
    theme_category: str = ""
    editorial_tone: str = ""
    aspect_ratio: str = "16:9"
    image_width: int = 1920
    image_height: int = 1080


@dataclass(frozen=True)
class ImageGenerationResult:
    local_path: Path
    attribution: str
    license: str
    title: str
    provider_plan: str


class ImageProvider(Protocol):
    plan_id: str

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult | None:
        """Génère une image et la sauvegarde localement."""
