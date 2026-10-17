from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.core.api_keys import GcpCredentials
from agent.core.config import load_agent_config


@dataclass(frozen=True)
class ImageGenerationRequest:
    # Prompt envoyé tel quel au modèle (écrit par Claude, cf. studio/workspace/docs/ai-images.md).
    prompt: str
    output_dir: Path
    aspect_ratio: str = "16:9"
    image_width: int = 1920
    image_height: int = 1080
    fal_api_key: str | None = None
    gcp_credentials: GcpCredentials | None = None


@dataclass(frozen=True)
class ImageGenerationResult:
    local_path: Path
    attribution: str
    license: str
    title: str
    provider_plan: str


def ai_fallback_config() -> dict:
    """Section `media_sources.ai_fallback` de data/agent_config.json."""
    return load_agent_config().get("media_sources", {}).get("ai_fallback", {}) or {}


def ai_license_label() -> str:
    return str(ai_fallback_config().get("license", "synthetic-ai-generated"))
