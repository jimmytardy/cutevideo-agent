from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def synthesize_ssml(
    ssml: str,
    output_path: Path,
    voice: str,
    *,
    subscription_key: str | None = None,
    region: str | None = None,
) -> float:
    """Synthèse Azure Neural TTS depuis SSML."""
    import azure.cognitiveservices.speech as speechsdk

    from agent.core.config import settings

    speech_key = (subscription_key or settings.azure_speech_key or "").strip()
    speech_region = (region or settings.azure_speech_region).strip()
    if not speech_key:
        raise RuntimeError("Clé Azure Speech non configurée")

    speech_config = speechsdk.SpeechConfig(
        subscription=speech_key,
        region=speech_region,
    )
    speech_config.speech_synthesis_voice_name = voice

    tmp_path = output_path.with_suffix(".raw.wav")
    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(tmp_path))

    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, synthesizer.speak_ssml, ssml)

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = result.cancellation_details
        raise RuntimeError(
            f"Azure TTS échoué : {result.reason} — {details.error_details if details else ''}"
        )

    from agent.skills.audio.tts import normalize_wav

    await normalize_wav(tmp_path, output_path)
    tmp_path.unlink(missing_ok=True)

    from agent.skills.audio.tts import probe_duration

    duration = await probe_duration(output_path)
    logger.debug("Azure TTS généré : %.1f s → %s", duration, output_path)
    return duration
