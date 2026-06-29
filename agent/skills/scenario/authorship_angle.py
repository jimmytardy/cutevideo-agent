from __future__ import annotations

from typing import Any


def normalize_authorship_angle(
    data: dict[str, Any],
    *,
    content_plan: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Valide et normalise authorship_angle ; fallback sur content_plan.angle."""
    raw = data.get("authorship_angle") or {}
    if not isinstance(raw, dict):
        raw = {}

    plan = content_plan or {}
    fallback_angle = str(plan.get("angle") or "").strip()
    thesis = str(raw.get("thesis") or "").strip()
    reason = str(raw.get("reason_to_watch") or "").strip()
    intro_hook = str(raw.get("intro_hook") or "").strip()

    if not thesis and fallback_angle:
        thesis = fallback_angle.split("\n")[0][:200]
    if not reason and fallback_angle:
        reason = fallback_angle[:300]
    if not intro_hook and thesis:
        intro_hook = thesis

    return {
        "thesis": thesis,
        "reason_to_watch": reason,
        "intro_hook": intro_hook,
    }


def authorship_angle_is_valid(angle: dict[str, str]) -> bool:
    return bool((angle.get("thesis") or "").strip())


def format_editorial_format_block(content_plan: dict[str, Any] | None) -> str:
    if not content_plan:
        return ""
    fmt_id = content_plan.get("editorial_format_id") or ""
    intro = content_plan.get("intro_variant") or ""
    outro = content_plan.get("outro_variant") or ""
    note = content_plan.get("editorial_angle_note") or ""
    lines = [
        "FORMAT ÉDITORIAL ASSIGNÉ :",
        f"- Format : {content_plan.get('narrative_format', fmt_id)} ({fmt_id})",
    ]
    if intro:
        lines.append(f"- Variante intro : {intro}")
    if outro:
        lines.append(f"- Variante outro : {outro}")
    if note:
        lines.append(f"- Note d'angle (hint optionnel) : {note}")
    return "\n".join(lines) + "\n"
