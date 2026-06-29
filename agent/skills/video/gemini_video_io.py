from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from agent.core.json_parse import parse_gemini_response
from agent.core.llm_retry import retry_transient_sync

logger = logging.getLogger(__name__)

QUOTA_ERROR_KEYWORDS = ("429", "quota", "resource_exhausted", "billing", "rate limit", "out of credit")


def is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in QUOTA_ERROR_KEYWORDS)


def wait_for_active_file(client: Any, types: Any, uploaded: Any) -> Any:
    for _ in range(60):
        if uploaded.state == types.FileState.ACTIVE:
            return uploaded
        if uploaded.state == types.FileState.FAILED:
            raise RuntimeError(f"Gemini File API — traitement échoué : {uploaded.name}")
        time.sleep(5)
        uploaded = client.files.get(name=uploaded.name)
    raise RuntimeError("Gemini File API — timeout après 5 min de traitement")


def call_gemini_video_json(
    client: Any,
    types: Any,
    model_name: str,
    video_file: Any,
    prompt: str,
    *,
    response_schema: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    logger.info("Gemini : analyse vidéo avec %s (%s)", model_name, label)
    response = retry_transient_sync(
        lambda: client.models.generate_content(
            model=model_name,
            contents=[video_file, prompt],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=4096,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        ),
        label=f"{label}/{model_name}",
    )
    return parse_gemini_response(response, model_name)


async def analyze_video_json_with_gemini(
    video_path: Path,
    prompt: str,
    *,
    api_key: str,
    response_schema: dict[str, Any],
    model_name: str = "gemini-2.5-pro",
    fallback_model: str = "gemini-3.5-flash",
    label: str = "gemini_video",
) -> dict[str, Any]:
    """Upload une vidéo locale vers Gemini File API et retourne le JSON structuré."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai non installé — run: pip install google-genai"
        ) from exc

    def _upload_and_analyze() -> dict[str, Any]:
        client = genai.Client(api_key=api_key)
        logger.info("Gemini : upload vidéo %s", video_path)
        uploaded = client.files.upload(
            file=str(video_path),
            config=types.UploadFileConfig(mime_type="video/mp4"),
        )
        uploaded = wait_for_active_file(client, types, uploaded)

        try:
            return call_gemini_video_json(
                client,
                types,
                model_name,
                uploaded,
                prompt,
                response_schema=response_schema,
                label=label,
            )
        except Exception as primary_exc:
            if is_quota_error(primary_exc) and fallback_model and fallback_model != model_name:
                logger.warning(
                    "Gemini %s quota/crédit épuisé (%s) — fallback sur %s",
                    model_name,
                    primary_exc,
                    fallback_model,
                )
                return call_gemini_video_json(
                    client,
                    types,
                    fallback_model,
                    uploaded,
                    prompt,
                    response_schema=response_schema,
                    label=label,
                )
            raise
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    return await asyncio.to_thread(_upload_and_analyze)
