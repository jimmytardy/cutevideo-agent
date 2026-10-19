"""Lecture du JSON renvoyé par un LLM (agents Python : planner, distribution, réponses aux commentaires)."""

from __future__ import annotations

import json
from typing import Any


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Objet JSON d'une réponse LLM, bloc ``` toléré ; `ValueError` si ce n'est pas un objet."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("réponse LLM : objet JSON attendu")
    return data
