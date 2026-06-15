from __future__ import annotations

import re
import xml.sax.saxutils
from typing import Any

TONE_STYLE_MAP: dict[str, dict[str, str]] = {
    "humoristique": {"azure_style": "cheerful", "rate": "+10%", "pitch": "+2Hz"},
    "humour": {"azure_style": "cheerful", "rate": "+10%", "pitch": "+2Hz"},
    "pédagogique": {"azure_style": "narration-professional", "rate": "+0%", "pitch": "+0Hz"},
    "sérieux": {"azure_style": "newscast-formal", "rate": "-5%", "pitch": "+0Hz"},
    "documentaire": {"azure_style": "narration-professional", "rate": "+0%", "pitch": "+0Hz"},
}

MOOD_TO_AZURE: dict[str, dict[str, str]] = {
    "energique": {"azure_style": "excited", "rate": "+10%", "pitch": "+2Hz"},
    "calme": {"azure_style": "calm", "rate": "-5%", "pitch": "-1Hz"},
    "dramatique": {"azure_style": "sad", "rate": "-3%", "pitch": "-2Hz"},
    "mysterieux": {"azure_style": "whispering", "rate": "-8%", "pitch": "-2Hz"},
    "inspirant": {"azure_style": "empathetic", "rate": "+3%", "pitch": "+1Hz"},
    "humoristique": {"azure_style": "cheerful", "rate": "+10%", "pitch": "+2Hz"},
    "tension": {"azure_style": "terrified", "rate": "+5%", "pitch": "+1Hz"},
    "revelateur": {"azure_style": "empathetic", "rate": "+0%", "pitch": "+0Hz"},
}

PACE_TO_RATE: dict[str, str] = {
    "slow": "-8%",
    "normal": "+0%",
    "fast": "+12%",
}

EMOTION_TO_PITCH: dict[str, str] = {
    "serious": "+0Hz",
    "playful": "+3Hz",
    "dramatic": "-2Hz",
    "calm": "-1Hz",
    "excited": "+2Hz",
    "mysterious": "-2Hz",
    "empathetic": "+1Hz",
}

VALID_AZURE_STYLES: frozenset[str] = frozenset({
    "advertisement_upbeat",
    "affectionate",
    "angry",
    "assistant",
    "calm",
    "chat",
    "cheerful",
    "customerservice",
    "depressed",
    "disgruntled",
    "documentary-narration",
    "embarrassed",
    "empathetic",
    "envious",
    "excited",
    "fearful",
    "friendly",
    "gentle",
    "hopeful",
    "lyrical",
    "narration-professional",
    "narration-relaxed",
    "newscast",
    "newscast-casual",
    "newscast-formal",
    "poetry-reading",
    "sad",
    "serious",
    "shouting",
    "sports_commentary",
    "sports_commentary_excited",
    "terrified",
    "unfriendly",
    "whispering",
})

DEFAULT_STYLE = "narration-relaxed"
DEFAULT_RATE = "+0%"
DEFAULT_PITCH = "+0Hz"


def _escape(text: str) -> str:
    return xml.sax.saxutils.escape(text)


def _tone_defaults(editorial_tone: str) -> dict[str, str]:
    tone_lower = editorial_tone.lower()
    for key, values in TONE_STYLE_MAP.items():
        if key in tone_lower:
            return values
    return {"azure_style": DEFAULT_STYLE, "rate": DEFAULT_RATE, "pitch": DEFAULT_PITCH}


def _mood_defaults(mood: str) -> dict[str, str]:
    mood_lower = mood.lower().strip()
    return MOOD_TO_AZURE.get(mood_lower, {})


def _sanitize_style(style: str) -> str:
    normalized = style.strip().lower()
    if normalized in VALID_AZURE_STYLES:
        return normalized
    return DEFAULT_STYLE


def _resolve_prosody(
    *,
    delivery_style: dict[str, Any] | None,
    mood: str,
    editorial_tone: str,
    default_style: str,
    default_rate: str,
    default_pitch: str,
) -> tuple[str, str, str]:
    """Résout style/rate/pitch : delivery_style > mood > editorial_tone > channel defaults."""
    ds = delivery_style or {}
    tone_defaults = _tone_defaults(editorial_tone)
    mood_defaults = _mood_defaults(mood)

    style = _sanitize_style(
        str(ds.get("azure_style") or mood_defaults.get("azure_style") or tone_defaults.get("azure_style", DEFAULT_STYLE))
    )
    pace = str(ds.get("pace") or "").lower()
    rate = PACE_TO_RATE.get(pace) or mood_defaults.get("rate") or tone_defaults.get("rate", DEFAULT_RATE)
    emotion = str(ds.get("emotion") or "").lower()
    pitch = (
        str(ds.get("pitch"))
        if ds.get("pitch")
        else EMOTION_TO_PITCH.get(emotion)
        or mood_defaults.get("pitch")
        or tone_defaults.get("pitch", DEFAULT_PITCH)
    )

    # Defaults chaîne (prioritaires seulement si explicitement configurés)
    if default_style != DEFAULT_STYLE:
        style = _sanitize_style(default_style)
    if default_rate != DEFAULT_RATE:
        rate = default_rate
    if default_pitch != DEFAULT_PITCH:
        pitch = default_pitch

    # delivery_style segment repasse en priorité absolue sur les defaults chaîne
    if ds.get("azure_style"):
        style = _sanitize_style(str(ds["azure_style"]))
    if pace in PACE_TO_RATE:
        rate = PACE_TO_RATE[pace]
    if ds.get("pitch"):
        pitch = str(ds["pitch"])

    return style, rate, pitch


def _insert_pauses(escaped_body: str) -> str:
    """Ajoute des pauses SSML après ponctuation forte."""
    return re.sub(
        r"([.!?])(\s)",
        r"\1<break time='300ms'/>\2",
        escaped_body,
    )


def _apply_emphasis(escaped_body: str, text: str, emphasis_words: list[Any]) -> str:
    body = escaped_body
    for word in emphasis_words:
        if word and str(word) in text:
            body = body.replace(
                _escape(str(word)),
                f"<emphasis level='moderate'>{_escape(str(word))}</emphasis>",
            )
    return body


def is_dragon_hd_voice(voice: str) -> bool:
    """True pour les voix Azure Dragon HD (express-as non supporté)."""
    return "DragonHD" in voice


def _wrap_voice_body(voice: str, style: str, rate: str, pitch: str, body: str) -> str:
    if is_dragon_hd_voice(voice):
        return (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="fr-FR">'
            f'<voice name="{voice}">'
            f'<prosody rate="{rate}" pitch="{pitch}">{body}</prosody>'
            f"</voice></speak>"
        )
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="fr-FR">'
        f'<voice name="{voice}">'
        f'<mstts:express-as style="{style}">'
        f'<prosody rate="{rate}" pitch="{pitch}">{body}</prosody>'
        f"</mstts:express-as></voice></speak>"
    )


def build_azure_ssml(
    text: str,
    voice: str,
    *,
    delivery_style: dict[str, Any] | None = None,
    mood: str = "",
    editorial_tone: str = "",
    default_style: str = DEFAULT_STYLE,
    default_rate: str = DEFAULT_RATE,
    default_pitch: str = DEFAULT_PITCH,
    insert_pauses: bool = True,
) -> str:
    """Construit un document SSML Azure avec style par segment."""
    style, rate, pitch = _resolve_prosody(
        delivery_style=delivery_style,
        mood=mood,
        editorial_tone=editorial_tone,
        default_style=default_style,
        default_rate=default_rate,
        default_pitch=default_pitch,
    )

    body = _escape(text.strip())
    if insert_pauses:
        body = _insert_pauses(body)

    emphasis_words = (delivery_style or {}).get("emphasis_words") or []
    body = _apply_emphasis(body, text, emphasis_words)

    return _wrap_voice_body(voice, style, rate, pitch, body)
