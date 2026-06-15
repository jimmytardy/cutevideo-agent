from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.core.database import Scenario

if TYPE_CHECKING:
    from agent.core.channel_config import ChannelRuntimeConfig

_PRESERVED_SEGMENT_FIELDS = ("narration_text", "needs_voice", "needs_music", "duration_s")


def validate_segment_count_preserved(
    original_segments: list[dict[str, Any]],
    new_segments: list[dict[str, Any]],
    *,
    context: str,
) -> None:
    """Lève ValueError si le nombre de segments a changé après une réécriture."""
    if len(new_segments) != len(original_segments):
        raise ValueError(
            f"{context} : {len(new_segments)} segment(s) après traitement, "
            f"{len(original_segments)} attendu(s)"
        )


def validate_merged_segments(
    original_segments: list[dict[str, Any]],
    merged_segments: list[dict[str, Any]],
) -> None:
    """Vérifie que le merge diagram n'a pas effacé les métadonnées narration/voix."""
    if len(merged_segments) != len(original_segments):
        raise ValueError(
            f"Merge diagram invalide : {len(merged_segments)} segment(s) après merge, "
            f"{len(original_segments)} attendu(s)"
        )

    orig_by_order = {int(seg.get("order", 0) or 0): seg for seg in original_segments}
    for merged in merged_segments:
        order = int(merged.get("order", 0) or 0)
        orig = orig_by_order.get(order)
        if orig is None:
            raise ValueError(f"Merge diagram invalide : segment order={order} inconnu")

        for field in _PRESERVED_SEGMENT_FIELDS:
            if field not in orig:
                continue
            if orig[field] != merged.get(field):
                raise ValueError(
                    f"Merge diagram invalide : segment {order} — "
                    f"champ {field!r} modifié"
                )

        orig_narr = (str(orig.get("narration_text") or "")).strip()
        merged_narr = (str(merged.get("narration_text") or "")).strip()
        if orig_narr and not merged_narr:
            raise ValueError(
                f"Merge diagram invalide : segment {order} — narration_text effacée"
            )


def segment_has_phrase_anchors(segment: dict[str, Any]) -> bool:
    for beat in segment.get("visual_beats") or []:
        if isinstance(beat, dict) and (beat.get("phrase_anchor") or "").strip():
            return True
    return False


def scenario_expects_narration(segments: list[dict[str, Any]]) -> bool:
    """True si le scénario indique qu'une piste voix est attendue."""
    for seg in segments:
        if (seg.get("narration_text") or "").strip():
            return True
        if segment_has_phrase_anchors(seg):
            return True
    return False


def validate_scenario_integrity(
    scenario: Scenario,
    channel_config: ChannelRuntimeConfig,
) -> None:
    """Lève RuntimeError si le scénario est incohérent avant media_agent."""
    segments = list(scenario.segments or [])
    if not segments:
        raise RuntimeError("Scénario invalide avant media_agent : aucun segment")

    orders = [int(seg.get("order", 0) or 0) for seg in segments]
    if any(order < 1 for order in orders):
        raise RuntimeError("Scénario invalide avant media_agent : order segment invalide")
    if len(orders) != len(set(orders)):
        raise RuntimeError("Scénario invalide avant media_agent : orders dupliqués")

    for seg in segments:
        if not segment_has_phrase_anchors(seg):
            continue
        has_narration = bool((seg.get("narration_text") or "").strip())
        voice_off = seg.get("needs_voice") is False
        if not has_narration and not voice_off:
            order = seg.get("order", "?")
            raise RuntimeError(
                f"Scénario invalide avant media_agent : segment {order} avec phrase_anchor "
                "mais sans narration_text ni needs_voice=false"
            )

    if channel_config.production_mode != "shorts_only":
        if not any((seg.get("narration_text") or "").strip() for seg in segments):
            raise RuntimeError(
                "Scénario invalide avant media_agent : aucune narration_text "
                "(scénario probablement tronqué)"
            )
