from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from dataclasses import dataclass

from pydantic import field_validator
from pydantic_settings import BaseSettings


@dataclass
class StorageSettings:
    bucket: str
    region: str
    key_prefix: str
    presign_ttl_seconds: int
    endpoint_url: str | None
    delete_local_after_upload: bool
    retention_days: int
    max_storage_bytes: int
    storage_buffer_bytes: int


class Settings(BaseSettings):
    # IA
    anthropic_api_key: str

    # Base de données
    database_url: str = "postgresql+asyncpg://cutevideo:cutevideo@localhost:5432/cutevideo"
    redis_url: str = "redis://localhost:6379"

    # Sources médias libres
    unsplash_access_key: str = ""
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    freesound_api_key: str = ""
    europeana_api_key: str = ""

    # Plateformes de publication
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    instagram_access_token: str = ""
    instagram_page_id: str = ""

    composio_api_key: str = ""
    runway_api_key: str = ""
    google_gemini_api_key: str = ""
    fal_key: str = ""
    google_application_credentials: str = ""
    gcp_project_id: str = ""
    gcp_location: str = "europe-west1"
    media_public_base_url: str = "http://localhost:8000"
    api_base_url: str = "http://localhost:8000"
    youtube_oauth_redirect_uri: str = "http://localhost:8000/api/v1/channels/youtube/oauth/callback"

    s3_bucket: str = ""
    s3_region: str = "eu-west-3"
    s3_key_prefix: str = "cutevideo"
    s3_presign_ttl_seconds: int = 3600
    s3_endpoint_url: str = ""
    s3_delete_local_after_upload: bool = True
    storage_retention_days: int = 30
    s3_max_storage_bytes: int = 10 * 1024 * 1024 * 1024
    s3_storage_buffer_bytes: int = 500 * 1024 * 1024
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    storage_backend: str = "local"

    # API
    cors_origins: str = "http://localhost:3000"
    scheduler_enabled: bool = True

    # TTS
    edge_tts_voice: str = "fr-FR-DeniseNeural"
    azure_speech_key: str = ""
    azure_speech_region: str = "westeurope"
    tts_engine: str = "azure"

    # Runtime / Docker
    port: int = 3000
    internal_api_url: str = "http://127.0.0.1:8000"

    # Config pipeline
    whisper_model: str = "large-v3"
    max_critic_iterations: int = 5
    min_critic_score: int = 90
    min_short_structure_score: int = 15
    min_image_duration_s: int = 4
    config_path: str = "./data/agent_config.json"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("google_gemini_api_key")
    @classmethod
    def strip_gemini_api_key(cls, v: str) -> str:
        return v.strip()

    @field_validator("database_url")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL doit utiliser postgresql+asyncpg://")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_storage_settings() -> StorageSettings:
    global_cfg = load_agent_config().get("storage", {})
    return StorageSettings(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        key_prefix=settings.s3_key_prefix,
        presign_ttl_seconds=int(
            global_cfg.get("presign_ttl_seconds", settings.s3_presign_ttl_seconds)
        ),
        endpoint_url=settings.s3_endpoint_url or None,
        delete_local_after_upload=bool(
            global_cfg.get("delete_local_after_upload", settings.s3_delete_local_after_upload)
        ),
        retention_days=int(global_cfg.get("retention_days", settings.storage_retention_days)),
        max_storage_bytes=int(
            global_cfg.get("max_storage_bytes", settings.s3_max_storage_bytes)
        ),
        storage_buffer_bytes=int(
            global_cfg.get("storage_buffer_bytes", settings.s3_storage_buffer_bytes)
        ),
    )


def load_agent_config() -> dict[str, Any]:
    """Charge la configuration JSON des agents."""
    path = Path(get_settings().config_path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


settings = get_settings()
