from __future__ import annotations


def derive_crop_box(salient_box: list[float] | None) -> list[float] | None:
    """Dérive une crop_box normalisée 0–1 depuis salient_box."""
    if not salient_box or len(salient_box) < 4:
        return None
    try:
        return [max(0.0, min(1.0, float(v))) for v in salient_box[:4]]
    except (TypeError, ValueError):
        return None
