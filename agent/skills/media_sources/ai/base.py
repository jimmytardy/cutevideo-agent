from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.core.api_keys import GcpCredentials


@dataclass(frozen=True)
class ImageGenerationRequest:
    prompt: str
    output_dir: Path
    theme_category: str = ""
    editorial_tone: str = ""
    aspect_ratio: str = "16:9"
    image_width: int = 1920
    image_height: int = 1080
    visual_type: str = ""
    style_block: str = ""
    use_prompt_as_is: bool = False
    fal_api_key: str | None = None
    gcp_credentials: GcpCredentials | None = None
    # P3 — graine déterministe par entité récurrente pour stabiliser le rendu d'un plan
    # à l'autre (bible de sujet). None = graine aléatoire côté fournisseur.
    seed: int | None = None


@dataclass(frozen=True)
class ImageGenerationResult:
    local_path: Path
    attribution: str
    license: str
    title: str
    provider_plan: str
