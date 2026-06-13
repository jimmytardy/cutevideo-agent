from __future__ import annotations

import xml.sax.saxutils
from typing import Any

TONE_STYLE_MAP: dict[str, dict[str, str]] = {
    "humoristique": {"azure_style": "cheerful", "rate": "+10%", "pitch": "+2Hz"},
    "humour": {"azure_style": "cheerful", "rate": "+10%", "pitch": "+2Hz"},
    "pédagogique": {"azure_style": "narration-professional", "rate": "+0%", "pitch": "+0Hz"},
    "sérieux": {"azure_style": "newscast-formal", "rate": "-5%", "pitch": "+0Hz"},
    "documentaire": {"azure_style": "narration-professional", "rate": "+0%", "pitch": "+0Hz"},
}

PACE_RATE = {"fast": "+15%", "normal": "+0%", "slow": "-10%"}


def _escape(text: str) -> str:
    return xml.sax.saxutils.escape(text)


def _tone_defaults(editorial_tone: str) -> dict[str, str]:
    tone_lower = editorial_tone.lower()
    for key, values in TONE_STYLE_MAP.items():
        if key in tone_lower:
            return values
    return TONE_STYLE_MAP["pédagogique"]


def build_azure_ssml(
    text: str,
    voice: str,
    *,
    delivery_style: dict[str, Any] | None = None,
    editorial_tone: str = "",
    default_style: str = "narration-professional",
    default_rate: str = "+0%",
    default_pitch: str = "+0Hz",
) -> str:
    """Construit un document SSML Azure avec style expressif optionnel."""
    tone_defaults = _tone_defaults(editorial_tone)
    style = default_style
    rate = default_rate
    pitch = default_pitch

    if delivery_style:
        style = str(delivery_style.get("azure_style") or tone_defaults.get("azure_style") or style)
        pace = delivery_style.get("pace")
        if pace and pace in PACE_RATE:
            rate = PACE_RATE[str(pace)]
        else:
            rate = str(delivery_style.get("rate") or tone_defaults.get("rate") or rate)
        pitch = str(delivery_style.get("pitch") or tone_defaults.get("pitch") or pitch)
    else:
        style = tone_defaults.get("azure_style", style)
        rate = tone_defaults.get("rate", rate)
        pitch = tone_defaults.get("pitch", pitch)

    body = _escape(text.strip())
    emphasis_words = (delivery_style or {}).get("emphasis_words") or []
    for word in emphasis_words:
        if word and word in text:
            body = body.replace(_escape(str(word)), f"<emphasis level='moderate'>{_escape(str(word))}</emphasis>")

    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="fr-FR">'
        f'<voice name="{voice}">'
        f'<mstts:express-as style="{style}">'
        f'<prosody rate="{rate}" pitch="{pitch}">{body}</prosody>'
        f"</mstts:express-as></voice></speak>"
    )
