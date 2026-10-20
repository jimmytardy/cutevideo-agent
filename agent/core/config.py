from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from dataclasses import dataclass

from pydantic import field_validator
from pydantic_settings import BaseSettings


@dataclass
class PipelineSettings:
    min_free_disk_bytes: int
    queue_dequeue_max_attempts: int
    queue_blocked_backoff_seconds: int
    reconcile_interval_seconds: int


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
    # Les clés payantes (Anthropic, Gemini, fal, Azure, GCP) et les comptes de publication
    # (YouTube, Instagram) sont par utilisateur : table user_api_keys (agent/core/api_keys.py).

    # Base de données
    database_url: str = "postgresql+asyncpg://cutevideo:cutevideo@localhost:5432/cutevideo"
    redis_url: str = "redis://localhost:6379"

    # Sources médias libres
    unsplash_access_key: str = ""
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    coverr_api_key: str = ""
    freesound_api_key: str = ""
    europeana_api_key: str = ""

    # Plateformes de publication
    youtube_client_id: str = ""
    youtube_client_secret: str = ""

    composio_api_key: str = ""
    composio_tiktok_auth_config_id: str = ""
    gcp_location: str = "europe-west1"
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

    # API
    cors_origins: str = "http://localhost:3000"
    scheduler_enabled: bool = True

    # Auth multi-utilisateurs
    jwt_secret_key: str = "dev-change-me-in-production"
    jwt_expire_minutes: int = 60 * 24 * 7
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    api_keys_encryption_key: str = ""
    # Connexion par code Google Authenticator (TOTP) : clé base32 + seul e-mail qu'elle déverrouille.
    totp_secret: str = ""
    totp_login_email: str = ""

    # TTS
    azure_speech_region: str = "westeurope"
    tts_engine: str = "azure"

    # Config pipeline
    config_path: str = "./data/agent_config.json"
    pipeline_min_free_disk_bytes: int = 5 * 1024 * 1024 * 1024
    pipeline_queue_dequeue_max_attempts: int = 50
    pipeline_queue_blocked_backoff_seconds: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @field_validator("database_url")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL doit utiliser postgresql+asyncpg://")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_pipeline_settings() -> PipelineSettings:
    global_cfg = load_agent_config().get("pipeline", {})
    return PipelineSettings(
        min_free_disk_bytes=int(
            global_cfg.get("min_free_disk_bytes", settings.pipeline_min_free_disk_bytes)
        ),
        queue_dequeue_max_attempts=int(
            global_cfg.get(
                "queue_dequeue_max_attempts",
                settings.pipeline_queue_dequeue_max_attempts,
            )
        ),
        queue_blocked_backoff_seconds=int(
            global_cfg.get(
                "queue_blocked_backoff_seconds",
                settings.pipeline_queue_blocked_backoff_seconds,
            )
        ),
        reconcile_interval_seconds=int(
            global_cfg.get("reconcile_interval_seconds", 600)
        ),
    )


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


_agent_config_cache: tuple[Path, int, dict[str, Any]] | None = None


def load_agent_config() -> dict[str, Any]:
    """Configuration JSON des agents (data/agent_config.json).

    Relue seulement si le fichier a changé (mtime) ; renvoie une copie que
    l'appelant peut modifier librement.
    """
    global _agent_config_cache
    path = Path(get_settings().config_path)
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    if _agent_config_cache is None or _agent_config_cache[:2] != (path, mtime):
        with path.open(encoding="utf-8") as f:
            _agent_config_cache = (path, mtime, json.load(f))
    return copy.deepcopy(_agent_config_cache[2])


def save_agent_config(config: dict[str, Any]) -> None:
    path = Path(get_settings().config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


settings = get_settings()
