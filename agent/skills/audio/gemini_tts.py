from __future__ import annotations

import asyncio
import logging
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_GEMINI_VOICE = "Leda"
DEFAULT_GEMINI_LANGUAGE = "fr"

MOOD_TO_INSTRUCTION: dict[str, str] = {
    "energique": "ton énergique et dynamique",
    "calme": "ton calme et posé",
    "dramatique": "ton dramatique et captivant",
    "mysterieux": "ton mystérieux et intrigant",
    "inspirant": "ton inspirant et chaleureux",
    "humoristique": "ton léger et humoristique",
    "tension": "ton tendu et suspenseful",
    "revelateur": "ton révélateur et empathique",
}

TONE_TO_INSTRUCTION: dict[str, str] = {
    "humoristique": "ton léger et humoristique",
    "humour": "ton léger et humoristique",
    "pédagogique": "ton pédagogique et clair",
    "sérieux": "ton sérieux et documentaire",
    "documentaire": "ton documentaire professionnel",
}


def build_gemini_tts_prompt(
    text: str,
    *,
    mood: str = "",
    editorial_tone: str = "",
    tts_style: str = "",
) -> str:
    """Construit un prompt naturel pour piloter l'expressivité Gemini TTS."""
    instructions: list[str] = ["Narration en français pour une vidéo éducative."]

    tone_key = editorial_tone.strip().lower()
    if tone_key and tone_key in TONE_TO_INSTRUCTION:
        instructions.append(TONE_TO_INSTRUCTION[tone_key])

    mood_key = mood.strip().lower()
    if mood_key and mood_key in MOOD_TO_INSTRUCTION:
        instructions.append(MOOD_TO_INSTRUCTION[mood_key])

    if tts_style and tts_style not in ("narration-professional", "default"):
        instructions.append(f"style vocal : {tts_style.replace('-', ' ')}")

    style_block = " ".join(instructions)
    return f"{style_block}\n\nLis exactement le texte suivant, sans rien ajouter ni modifier :\n{text}"


def _write_pcm_wav(path: Path, pcm: bytes, *, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)


async def synthesize_gemini_tts(
    text: str,
    output_path: Path,
    *,
    voice: str = DEFAULT_GEMINI_VOICE,
    model: str = DEFAULT_GEMINI_TTS_MODEL,
    language_code: str = DEFAULT_GEMINI_LANGUAGE,
    mood: str = "",
    editorial_tone: str = "",
    tts_style: str = "",
    api_key: str,
) -> float:
    """Synthèse Gemini Flash TTS → WAV normalisé 48 kHz."""
    if not api_key.strip():
        raise RuntimeError("Clé Gemini non configurée pour la synthèse TTS")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai non installé — pip install google-genai") from exc

    prompt = build_gemini_tts_prompt(
        text,
        mood=mood,
        editorial_tone=editorial_tone,
        tts_style=tts_style,
    )
    client = genai.Client(api_key=api_key.strip())

    def _call() -> object:
        return client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    language_code=language_code,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice,
                        )
                    ),
                ),
            ),
        )

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, _call)

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        raise RuntimeError("Gemini TTS : réponse vide")

    parts = candidates[0].content.parts or []
    audio_data: bytes | None = None
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is not None and inline.data:
            audio_data = inline.data
            break

    if not audio_data:
        raise RuntimeError("Gemini TTS : aucune donnée audio dans la réponse")

    tmp_path = output_path.with_suffix(".gemini.wav")
    _write_pcm_wav(tmp_path, audio_data)

    from agent.skills.audio.tts import normalize_wav, probe_duration

    await normalize_wav(tmp_path, output_path)
    tmp_path.unlink(missing_ok=True)

    duration = await probe_duration(output_path)
    logger.debug("Gemini TTS généré : %.1f s → %s (voix=%s)", duration, output_path, voice)
    return duration
