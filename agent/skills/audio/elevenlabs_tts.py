"""Synthèse ElevenLabs avec la clé du propriétaire de la chaîne (jamais de clé de plateforme)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from agent.core.llm_retry import retry_transient_async
from agent.skills.video.ffmpeg_runtime import probe_duration

logger = logging.getLogger(__name__)

DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"
# MP3 : le WAV 44,1 kHz est réservé au forfait Pro ; `normalize_wav` convertit ensuite en WAV 48 kHz.
OUTPUT_FORMAT = "mp3_44100_128"
_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
_TIMEOUT_S = 120.0
SPEED_MIN = 0.7
SPEED_MAX = 1.2
_RATE_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*%\s*$")

# Remplacé par un httpx.MockTransport dans les tests.
_transport: httpx.AsyncBaseTransport | None = None


class ElevenLabsError(RuntimeError):
    """Refus ou panne d'ElevenLabs.

    `status_code` décide des relances (`is_transient_llm_error`). Le message ne contient que le statut et le code
    d'erreur : le texte libre de l'API pourrait contenir un nombre que la détection par mots-clés prendrait pour
    une erreur temporaire (« 500 crédits »), et ferait relancer un refus définitif.
    """

    def __init__(self, status_code: int, code: str = "") -> None:
        self.status_code = status_code
        self.error_code = code
        super().__init__(f"ElevenLabs a refusé la synthèse ({status_code}{f' {code}' if code else ''})")


def rate_to_speed(rate: str) -> float:
    """`+10%` → 1.1, dans la plage acceptée par l'API ; un débit illisible vaut la vitesse normale."""
    match = _RATE_RE.match(rate or "")
    if not match:
        return 1.0
    return round(min(SPEED_MAX, max(SPEED_MIN, 1 + float(match.group(1)) / 100)), 3)


def _error_code(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    if not isinstance(detail, dict):
        return ""
    return str(detail.get("code") or detail.get("status") or "")


async def _request(url: str, headers: dict[str, str], body: dict[str, Any]) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=_transport) as client:
            response = await client.post(url, params={"output_format": OUTPUT_FORMAT}, headers=headers, json=body)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:  # la requête n'est pas partie : relance sans frais
        raise ElevenLabsError(503, type(exc).__name__) from exc
    except httpx.TransportError as exc:
        # Requête peut-être déjà facturée : pas de relance sur le crédit du propriétaire, on passe au secours.
        raise RuntimeError(f"ElevenLabs n'a pas répondu ({type(exc).__name__})") from exc
    if not response.is_success:
        raise ElevenLabsError(response.status_code, _error_code(response))
    return response.content


async def synthesize_elevenlabs_tts(
    text: str,
    output_path: Path,
    *,
    voice: str,
    api_key: str | None,
    model: str = DEFAULT_ELEVENLABS_MODEL,
    rate: str = "+0%",
    previous_text: str = "",
    next_text: str = "",
    mastering: dict[str, Any] | None = None,
) -> float:
    """Écrit le WAV normalisé et renvoie sa durée.

    Sans clé ou sans voix : lève une erreur, jamais de repli ici. C'est `studio.tools tts` qui passe alors à la voix
    de secours de la chaîne ; un remplacement silencieux la court-circuiterait.
    """
    from agent.skills.audio.tts import normalize_wav

    key = (api_key or "").strip()
    voice_id = (voice or "").strip()
    if not key:
        raise RuntimeError("Clé ElevenLabs non configurée (Compte → Clés API)")
    if not voice_id:
        raise RuntimeError("Voix ElevenLabs non renseignée (voice_id)")

    body: dict[str, Any] = {"text": text, "model_id": model, "voice_settings": {"speed": rate_to_speed(rate)}}
    # Synthèse ligne par ligne : le contexte garde une intonation continue d'une ligne à l'autre.
    if previous_text:
        body["previous_text"] = previous_text
    if next_text:
        body["next_text"] = next_text
    url = f"{_API_URL}/{quote(voice_id, safe='')}"
    headers = {"xi-api-key": key}
    audio = await retry_transient_async(lambda: _request(url, headers, body), label="elevenlabs-tts")

    tmp_mp3 = output_path.with_suffix(".mp3")
    tmp_mp3.write_bytes(audio)
    try:
        await normalize_wav(tmp_mp3, output_path, mastering=mastering)
    finally:
        tmp_mp3.unlink(missing_ok=True)
    duration = await probe_duration(output_path)
    logger.debug("TTS ElevenLabs généré : %.1f s → %s", duration, output_path)
    return duration
