from __future__ import annotations

import asyncio
import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.llm_retry import MAX_TRANSIENT_RETRIES, retry_transient_sync

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
# Sur Vertex AI, les modèles TTS ne portent pas les mêmes noms que sur AI Studio.
DEFAULT_VERTEX_TTS_MODEL = "gemini-2.5-flash-tts"
# Puck (« dynamique ») : Leda (« jeune ») rendait les Shorts trop posés.
DEFAULT_GEMINI_VOICE = "Puck"
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


def rate_instruction(rate: str) -> str | None:
    """Consigne de débit en langage naturel à partir du réglage `--rate` (`+10%`) : Gemini n'a pas de
    paramètre de vitesse, c'est le seul levier (edge/Azure l'appliquent directement)."""
    try:
        pct = int(str(rate or "").strip().replace("%", "").replace("+", "") or 0)
    except ValueError:
        return None
    # Consigne continue (pas de paliers) : une emphase par ligne (`[rate=-4%]`) ne doit pas faire sauter le rythme
    # d'une phrase à l'autre une fois les lignes recollées.
    if pct > 0:
        return f"Débit : environ {pct} % plus vite qu'une lecture normale, sans avaler les syllabes."
    if pct < 0:
        return f"Débit : environ {-pct} % plus lent qu'une lecture normale, pour laisser respirer le propos."
    return None


def build_gemini_tts_prompt(
    text: str,
    *,
    mood: str = "",
    editorial_tone: str = "",
    tts_style: str = "",
    rate: str = "+0%",
) -> str:
    """Construit un prompt naturel pour piloter l'expressivité Gemini TTS.

    Gemini n'accepte pas de SSML : l'intonation et le rythme passent uniquement par ces instructions en
    langage naturel. Base « Short vertical » (rythme soutenu, énergie, intonation variée), puis le débit
    demandé, le ton éditorial et le mood (énergique par défaut : un Short sans relief perd le spectateur).
    """
    instructions: list[str] = [
        "Narration en français d'un Short vertical : rythme soutenu et vivant, énergie constante du début à la fin.",
        "Articulation nette, pauses brèves à la ponctuation, intonation variée : on appuie les chiffres, "
        "on monte sur les questions, on marque les révélations.",
    ]
    if rate_hint := rate_instruction(rate):
        instructions.append(rate_hint)

    tone_key = editorial_tone.strip().lower()
    if tone_key and tone_key in TONE_TO_INSTRUCTION:
        instructions.append(TONE_TO_INSTRUCTION[tone_key])

    mood_key = mood.strip().lower()
    if not mood_key:
        instructions.append(MOOD_TO_INSTRUCTION["energique"])  # un Short sans relief perd le spectateur
    else:
        instructions.append(MOOD_TO_INSTRUCTION.get(mood_key) or f"ton {mood_key}")  # mood libre : transmis tel quel

    if tts_style and tts_style not in ("narration-professional", "default"):
        instructions.append(f"style vocal : {tts_style.replace('-', ' ')}")

    style_block = " ".join(instructions)
    return f"{style_block}\n\nLis exactement le texte suivant, sans rien ajouter ni modifier :\n{text}"


@dataclass(frozen=True)
class VertexTarget:
    """Gemini TTS servi par Vertex AI avec le compte de service de l'utilisateur."""

    credentials_json: str
    location: str | None
    model: str = DEFAULT_VERTEX_TTS_MODEL


def vertex_tts_target(credentials_json: str | None, location: str | None = None) -> VertexTarget | None:
    """Cible Vertex de la voix (None sans compte GCP).

    Modèle et région viennent de `data/agent_config.json → tts.gemini.vertex_model / vertex_location` :
    le modèle TTS n'est pas servi dans toutes les régions, la région du compte ne sert qu'à défaut.
    """
    if not (credentials_json or "").strip():
        return None
    from agent.core.config import load_agent_config

    cfg = load_agent_config().get("tts", {}).get("gemini", {})
    return VertexTarget(
        credentials_json=credentials_json.strip(),
        location=str(cfg.get("vertex_location") or "").strip() or location,
        model=str(cfg.get("vertex_model") or "").strip() or DEFAULT_VERTEX_TTS_MODEL,
    )


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
    api_key: str | None = None,
    vertex: VertexTarget | None = None,
    mastering: dict[str, Any] | None = None,
    rate: str = "+0%",
    transient_retries: int = MAX_TRANSIENT_RETRIES,
) -> float:
    """Synthèse Gemini Flash TTS → WAV normalisé 48 kHz.

    Avec la clé Gemini (`api_key`) si elle est fournie, sinon via Vertex AI (`vertex`, dont le
    modèle remplace `model`).
    """
    key = (api_key or "").strip()
    if not key and vertex is None:
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
        rate=rate,
    )
    if key:
        client = genai.Client(api_key=key)
    else:
        from agent.core.vertex import vertex_genai_client

        client = vertex_genai_client(vertex.credentials_json, vertex.location)
        model = vertex.model

    def _call() -> object:
        return retry_transient_sync(
            lambda: client.models.generate_content(
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
            ),
            label="gemini_tts",
            max_retries=transient_retries,
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

    from agent.skills.audio.tts import normalize_wav
    from agent.skills.video.ffmpeg_runtime import probe_duration

    await normalize_wav(tmp_path, output_path, mastering=mastering)
    tmp_path.unlink(missing_ok=True)

    duration = await probe_duration(output_path)
    logger.debug("Gemini TTS généré : %.1f s → %s (voix=%s)", duration, output_path, voice)
    return duration
