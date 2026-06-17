from __future__ import annotations

from typing import Any

"""P6 — Direction voix sur retour critique.

Quand le `critic` route vers `narrator_agent` parce que l'expressivité vocale est
jugée trop plate, re-synthétiser avec le *même* `delivery_style` reproduit le même
résultat monotone. Cette passe déterministe varie réellement `pace` / `emotion` /
`azure_style` **par segment** (et à chaque itération du critique) avant la
re-synthèse, en restant cohérente avec le `mood` du segment.
"""

# Moods « sombres / tendus » : on garde une palette grave plutôt que joviale.
_DARK_MOODS: frozenset[str] = frozenset({
    "tension", "dramatique", "mysterieux", "mystérieux", "sombre", "suspense",
    "dramatic", "mysterious", "dark", "tense", "tragique",
})

# Styles Azure expressifs (sous-ensemble de VALID_AZURE_STYLES) par registre.
_DARK_STYLES: tuple[str, ...] = ("serious", "whispering", "sad", "terrified")
_DARK_EMOTIONS: tuple[str, ...] = ("dramatic", "mysterious", "serious")
_DARK_PACES: tuple[str, ...] = ("slow", "normal", "slow")

_BRIGHT_STYLES: tuple[str, ...] = ("excited", "cheerful", "hopeful", "empathetic", "friendly")
_BRIGHT_EMOTIONS: tuple[str, ...] = ("excited", "playful", "empathetic")
_BRIGHT_PACES: tuple[str, ...] = ("fast", "normal", "fast", "slow")


def direct_voice_for_revision(
    delivery_style: dict[str, Any] | None,
    *,
    segment_index: int,
    iteration: int = 1,
    mood: str = "",
) -> dict[str, Any]:
    """Renvoie un `delivery_style` plus expressif et varié pour une re-synthèse critique.

    - `segment_index` : décale la rotation entre segments (segments adjacents diffèrent).
    - `iteration` : décale la rotation entre passages du critique (un nouvel essai diffère
      du précédent même pour le même segment).
    - `mood` : choisit la palette (sombre/tendu vs lumineux/neutre).

    `emphasis_words` et autres champs existants sont préservés.
    """
    ds = dict(delivery_style or {})
    is_dark = mood.strip().lower() in _DARK_MOODS

    styles = _DARK_STYLES if is_dark else _BRIGHT_STYLES
    emotions = _DARK_EMOTIONS if is_dark else _BRIGHT_EMOTIONS
    paces = _DARK_PACES if is_dark else _BRIGHT_PACES

    rot = max(segment_index, 0) + max(iteration - 1, 0)
    ds["azure_style"] = styles[rot % len(styles)]
    ds["emotion"] = emotions[rot % len(emotions)]
    ds["pace"] = paces[rot % len(paces)]
    return ds
