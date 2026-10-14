"""Filtres ffmpeg Ken Burns (zoom lent, recadrage centré ou sur un point d'intérêt) pour les clips image."""

from __future__ import annotations


def _even(value: int) -> int:
    """Arrondit à un entier pair (requis par libx264 pour les dimensions)."""
    return int(value) // 2 * 2


def build_static_filter(width: int, height: int, fps: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},fps={fps}"
    )


def _focus_crop_exprs(motion_focus: list[float] | None) -> tuple[str, str]:
    if not motion_focus or len(motion_focus) < 2:
        return "(in_w-out_w)/2", "(in_h-out_h)/2"
    if len(motion_focus) >= 4:
        fcx = f"({motion_focus[0]}+{motion_focus[2]}/2)"
        fcy = f"({motion_focus[1]}+{motion_focus[3]}/2)"
    else:
        fcx, fcy = str(motion_focus[0]), str(motion_focus[1])
    x_expr = f"max(0\\,min({fcx}*in_w-out_w/2\\,in_w-out_w))"
    y_expr = f"max(0\\,min({fcy}*in_h-out_h/2\\,in_h-out_h))"
    return x_expr, y_expr


def build_zoom_filter(
    width: int,
    height: int,
    fps: int,
    n_frames: int,
    *,
    zoom_factor: float,
    pan_enabled: bool,
    pan_direction: int,
    motion_focus: list[float] | None = None,
) -> str:
    """Filtre Ken Burns : zoom linéaire centré via crop+scale (sans zoompan).

    zoompan arrondit les coordonnées à l'entier à chaque frame, ce qui produit
    un tremblement visible. On zoome en cropant une fenêtre rétrécissante sur
    une image sur-échantillonnée, puis on scale en Lanczos vers la taille cible.
    """
    if zoom_factor <= 0:
        return build_static_filter(width, height, fps)

    # Suréchantillonnage léger : le zoom max ne dépasse ~1+zoom_factor (≈1.03),
    # donc 1.5x suffit pour rester net. /!\ Le `scale ... eval=frame` ci-dessous
    # rééchantillonne (Lanczos) CHAQUE frame ; un facteur élevé (ex. 4x → 8K) sature
    # CPU/RAM et fait freezer la machine. Garder ce facteur bas.
    prescale_w = _even(width * 3 // 2)
    prescale_h = _even(height * 3 // 2)
    # crop n'évalue w/h qu'une fois à l'init — pas de zoom temporel possible.
    # On agrandit l'image via scale (eval=frame, variable n), puis on recadre au centre.
    z = f"(1+{zoom_factor}*n/{n_frames})"
    scale_w = f"trunc(iw*{z}/2)*2"
    scale_h = f"trunc(ih*{z}/2)*2"

    base_x, base_y = _focus_crop_exprs(motion_focus)
    if pan_enabled and pan_direction != 0:
        pan_expr = f"{pan_direction * 40}*n/{n_frames}"
        x_expr = f"{base_x}+({pan_expr})"
        y_expr = base_y
    else:
        x_expr, y_expr = base_x, base_y

    return (
        f"scale={prescale_w}:{prescale_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={prescale_w}:{prescale_h},"
        f"scale=w='{scale_w}':h='{scale_h}':eval=frame:flags=lanczos,"
        f"crop={prescale_w}:{prescale_h}:x='{x_expr}':y='{y_expr}',"
        f"scale={width}:{height}:flags=lanczos,fps={fps}"
    )
