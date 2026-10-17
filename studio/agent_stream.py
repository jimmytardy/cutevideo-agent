"""Trace d'exécution d'un sous-agent Claude Studio, affichée en terminal dans le dashboard.

Une ligne = un événement : texte brut (`--- Démarrage … ---`) ou `@agent-stream:{json}` avec `type` ∈
thinking, assistant, tool_call, task, error. `coalesce()` fusionne en place l'appel d'outil et son résultat
(même `callId`), les textes consécutifs d'un même type non terminés, et garde une seule ligne `task`
(progression : tokens, nombre d'outils, durée). Même algorithme côté client : `dashboard/lib/agentStream.ts`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

PREFIX = "@agent-stream:"
MAX_LINES = 2000
MAX_BYTES = 500_000
_MAX_RESULT_CHARS = 2000
_MAX_ARG_CHARS = 600


def encode(event: dict[str, Any]) -> str:
    return PREFIX + json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def parse_line(line: str) -> dict[str, Any] | None:
    """Événement structuré, ou None pour une ligne brute (ou un JSON invalide)."""
    if not line.startswith(PREFIX):
        return None
    try:
        event = json.loads(line[len(PREFIX):])
    except ValueError:
        return None
    return event if isinstance(event, dict) and isinstance(event.get("type"), str) else None


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}… (+{len(text) - limit} car.)"


def _short_args(args: Any, run_dir: str) -> Any:
    """Arguments lisibles : chemins relatifs au run dir, longues valeurs (contenu d'un Write…) tronquées."""
    if not isinstance(args, dict):
        return args
    prefix = run_dir.rstrip("/") + "/" if run_dir else ""
    short: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            if prefix and value.startswith(prefix):
                value = value[len(prefix):]
            value = _clip(value, _MAX_ARG_CHARS)
        short[key] = value
    return short


def stream_lines(
    msg: dict[str, Any], *, run_dir: str = "", result_text: Callable[[Any], str] | None = None
) -> list[str]:
    """Lignes d'un message stream-json appartenant à un sous-agent.

    `result_text` extrait le texte d'un `tool_result` (`studio.launcher._tool_result_text`).
    """
    mtype = msg.get("type")
    if mtype == "system" and msg.get("subtype") == "task_progress":
        usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
        return [encode({
            "type": "task",
            "description": str(msg.get("description") or ""),
            "tokens": usage.get("total_tokens"),
            "tool_uses": usage.get("tool_uses"),
            "duration_ms": usage.get("duration_ms"),
        })]
    if mtype == "system" and msg.get("subtype") == "permission_denied":
        return [encode({"type": "error", "text": f"Outil refusé : {msg.get('tool_name', '')}"})]

    message = msg.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    lines: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if mtype == "assistant" and btype == "thinking":
            text = str(block.get("thinking") or "").strip()
            if text:  # réflexion souvent masquée (texte vide, signature seule)
                lines.append(encode({"type": "thinking", "text": text, "done": True}))
        elif mtype == "assistant" and btype == "text":
            text = str(block.get("text") or "").strip()
            if text:
                lines.append(encode({"type": "assistant", "text": text, "done": True}))
        elif mtype == "assistant" and btype == "tool_use":
            lines.append(encode({
                "type": "tool_call",
                "callId": block.get("id"),
                "name": block.get("name", ""),
                "status": "running",
                "args": _short_args(block.get("input"), run_dir),
            }))
        elif mtype == "user" and btype == "tool_result":
            text = result_text(block.get("content")) if result_text else str(block.get("content") or "")
            lines.append(encode({
                "type": "tool_call",
                "callId": block.get("tool_use_id"),
                "status": "error" if block.get("is_error") else "completed",
                "result": _clip(text, _MAX_RESULT_CHARS),
            }))
    return lines


def merge_stream_text(old: str, new: str) -> str:
    """Fragment cumulatif (remplace), déjà contenu (garde) ou delta (concatène)."""
    if new.startswith(old):
        return new
    if new in old:
        return old
    return old + new


def _merge_tool(prev: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = {**prev, **{k: v for k, v in new.items() if v is not None}}
    if "args" in prev:
        merged["args"] = prev["args"]
    return merged


def coalesce(buf: list[str], line: str) -> str:
    """Ajoute `line` à `buf` ou fusionne avec une ligne existante ; renvoie la ligne résultante."""
    event = parse_line(line)
    if event is None:
        buf.append(line)
        return line
    etype = event["type"]

    if etype in ("thinking", "assistant") and buf:
        prev = parse_line(buf[-1])
        if prev and prev["type"] == etype and not prev.get("done"):
            merged = encode({**prev, **event, "text": merge_stream_text(str(prev.get("text", "")), str(event.get("text", "")))})
            buf[-1] = merged
            return merged

    if etype == "task":
        for i in range(len(buf) - 1, -1, -1):
            prev = parse_line(buf[i])
            if prev and prev["type"] == "task":
                buf[i] = line
                return line

    if etype == "tool_call":
        call_id = event.get("callId")
        for i in range(len(buf) - 1, -1, -1):
            prev = parse_line(buf[i])
            if not prev or prev["type"] != "tool_call":
                continue
            same = (
                prev.get("callId") == call_id
                if call_id
                else not prev.get("callId") and prev.get("status") == "running" and prev.get("name") == event.get("name")
            )
            if same:
                merged = encode(_merge_tool(prev, event))
                buf[i] = merged
                return merged

    buf.append(line)
    return line


def trim(buf: list[str], *, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> list[str]:
    """Plafonne la trace : retire les lignes les plus anciennes (10 % à la fois tant que trop lourde)."""
    lines = buf[-max_lines:]
    while lines and sum(len(line.encode("utf-8")) for line in lines) > max_bytes:
        lines = lines[max(1, len(lines) // 10):]
    return lines
