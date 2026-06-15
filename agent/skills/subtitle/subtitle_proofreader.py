from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

PROOFREAD_SYSTEM = """Tu corriges UNIQUEMENT l'orthographe et la grammaire des sous-titres.
Ne change pas le sens. Ne modifie pas les timestamps.
Retourne UNIQUEMENT du JSON valide."""

PROOFREAD_PROMPT = """Corrige les fautes dans ces segments de sous-titres (français).

Segments (JSON) :
{segments_json}

Retourne le même tableau avec "text" corrigé, start/end inchangés :
[
  {{"start": 0.0, "end": 2.5, "text": "..."}}
]"""


async def proofread_subtitle_segments(
    segments: list[dict[str, Any]],
    *,
    call_llm: Any,
) -> list[dict[str, Any]]:
    """Relecture orthographique LLM des segments Whisper."""
    if not segments:
        return segments
    prompt = PROOFREAD_PROMPT.format(
        segments_json=json.dumps(segments[:200], ensure_ascii=False, indent=2),
    )
    try:
        raw = await call_llm(prompt, system=PROOFREAD_SYSTEM, max_tokens=4096)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        corrected = json.loads(raw)
        if isinstance(corrected, list) and len(corrected) == len(segments):
            return corrected
    except Exception as exc:
        logger.warning("Proofread sous-titres échoué : %s", exc)
    return segments
