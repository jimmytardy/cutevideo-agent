from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

# Champs tableau touchés par la corruption Gemini grounding (:." au lieu de : [)
DEFAULT_GEMINI_ARRAY_FIELDS: tuple[str, ...] = (
    "key_facts",
    "visual_anchors",
    "common_misconceptions",
    "narrative_angles",
    "timeline",
    "sources",
    "scores",
)

_ARRAY_CORRUPTION_RES: dict[tuple[str, ...], re.Pattern[str]] = {}


def _array_corruption_pattern(fields: tuple[str, ...]) -> re.Pattern[str]:
    if fields not in _ARRAY_CORRUPTION_RES:
        names = "|".join(re.escape(f) for f in fields)
        _ARRAY_CORRUPTION_RES[fields] = re.compile(rf'"({names})":\."\s*,')
    return _ARRAY_CORRUPTION_RES[fields]


def normalize_parsed_value(parsed: Any) -> dict[str, Any] | None:
    """Extrait un dict depuis response.parsed (dict ou BaseModel Pydantic)."""
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, BaseModel):
        data = parsed.model_dump()
        if isinstance(data, dict):
            return data
    return None


def is_json_parse_failure(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return True
    return isinstance(exc, ValueError) and "JSON invalide" in str(exc)


def repair_gemini_array_corruption(
    raw: str,
    array_fields: tuple[str, ...] = DEFAULT_GEMINI_ARRAY_FIELDS,
) -> str:
    """Corrige la corruption ``"field":."`` observée avec Gemini grounding + schema."""
    if ':."' not in raw:
        return raw
    pattern = _array_corruption_pattern(array_fields)
    repaired_fields = {match.group(1) for match in pattern.finditer(raw)}
    if not repaired_fields:
        return raw

    text = pattern.sub(r'"\1": [', raw)
    lines = text.split("\n")
    out: list[str] = []
    open_field: str | None = None

    for line in lines:
        stripped = line.strip()
        if open_field is None:
            for field in repaired_fields:
                if (
                    f'"{field}": [' in line
                    and f'"{field}": [{{' not in line
                    and f'"{field}": ["' not in line
                ):
                    open_field = field
                    break
        elif re.match(r'"[a-z_]+"\s*:', stripped):
            field_name = re.match(r'"([a-z_]+)"', stripped)
            if field_name and field_name.group(1) != open_field:
                out.append("  ],")
                repaired_fields.discard(open_field)
                open_field = None
        out.append(line)

    if open_field is not None:
        out.append("  ]")
    return "\n".join(out)


def loads_json_object(
    text: str,
    *,
    repair_fn: Callable[[str], str] | None = repair_gemini_array_corruption,
) -> dict[str, Any]:
    """Parse un objet JSON avec réparation optionnelle et virgules traînantes."""
    last_exc: json.JSONDecodeError | None = None
    candidates = [text]
    if repair_fn is not None:
        candidates.append(repair_fn(text))

    for candidate in candidates:
        cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
        for payload in (candidate, cleaned):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                last_exc = exc
                continue
            if isinstance(data, dict):
                return data
            raise ValueError("JSON racine doit être un objet")
    if last_exc is not None:
        raise last_exc
    raise ValueError("JSON racine doit être un objet")


def parse_json_text(
    raw: str,
    source_name: str = "llm",
    *,
    repair_fn: Callable[[str], str] | None = repair_gemini_array_corruption,
) -> dict[str, Any]:
    """Extrait et parse un objet JSON depuis une réponse LLM (markdown, prose, etc.)."""
    text = raw.strip()
    block_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
    if block_match:
        try:
            return loads_json_object(block_match.group(1).strip(), repair_fn=repair_fn)
        except (json.JSONDecodeError, ValueError):
            pass

    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return loads_json_object(text[start : i + 1], repair_fn=repair_fn)
                    except (json.JSONDecodeError, ValueError):
                        break

    try:
        return loads_json_object(text, repair_fn=repair_fn)
    except json.JSONDecodeError as exc:
        snippet = text[:300].replace("\n", "\\n")
        raise ValueError(f"JSON invalide de {source_name} : {snippet}") from exc


def parse_gemini_response(
    response: Any,
    model_name: str,
    *,
    required_field: str | None = None,
    repair_fn: Callable[[str], str] | None = repair_gemini_array_corruption,
) -> dict[str, Any]:
    """Parse une réponse google-genai (response.parsed ou response.text)."""
    normalized = normalize_parsed_value(getattr(response, "parsed", None))
    if normalized is not None:
        if required_field is None or isinstance(normalized.get(required_field), list):
            return normalized

    raw = (getattr(response, "text", None) or "").strip()
    if not raw:
        raise ValueError(f"réponse vide de {model_name}")
    try:
        data = parse_json_text(raw, model_name, repair_fn=repair_fn)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalide de {model_name} : {raw[:200]}") from exc
    if required_field and not isinstance(data.get(required_field), list):
        raise ValueError(f"JSON invalide de {model_name} : champ {required_field} absent")
    return data
