from __future__ import annotations

import hashlib

"""P3 — Bible de sujet (cohérence inter-plans).

Les chaînes faceless IA souffrent du « patchwork » : une même entité récurrente
(personnage, animal, lieu) est ré-inventée à chaque plan. À défaut d'un
conditionnement par image de référence (img2img, non disponible sur l'endpoint
texte→image actuel), on stabilise le rendu en réutilisant une **graine
déterministe par entité** : les plans qui montrent la même entité partagent la
même graine de base, ce qui rapproche composition et style d'un plan à l'autre.

Le scoring best-of-N régénère plusieurs candidats par plan ; on décale donc la
graine par numéro d'essai pour conserver de la variété intra-plan tout en gardant
une graine de base commune inter-plans.
"""

# fal.ai accepte des graines entières ; on borne dans un intervalle sûr (uint31).
_SEED_MODULO = 2_000_000_000


def entity_seed(entity: str) -> int | None:
    """Graine déterministe et stable dérivée du nom d'une entité récurrente.

    Retourne ``None`` si l'entité est vide (→ graine aléatoire côté fournisseur).
    """
    normalized = (entity or "").strip().lower()
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return int(digest, 16) % _SEED_MODULO


def beat_subject_seed(subject_entity: str, beat_text: str) -> int | None:
    """Graine de l'entité sujet si le plan la met en scène, sinon ``None``.

    On ne fige la graine que pour les plans qui montrent réellement l'entité
    récurrente (heuristique : un mot significatif de l'entité apparaît dans le
    texte du plan). Les autres plans gardent une graine aléatoire (variété).
    """
    entity = (subject_entity or "").strip()
    if not entity:
        return None
    text = (beat_text or "").lower()
    tokens = [w for w in entity.lower().replace("-", " ").split() if len(w) > 3]
    if not tokens:
        # Entité mono-mot courte : exiger le nom complet.
        return entity_seed(entity) if entity.lower() in text else None
    if any(tok in text for tok in tokens):
        return entity_seed(entity)
    return None


def seed_for_attempt(base_seed: int | None, attempt: int) -> int | None:
    """Décale la graine de base par numéro d'essai (variété best-of-N).

    ``attempt`` commence à 1. L'essai 1 conserve exactement la graine de base
    (alignement inter-plans le plus fort) ; les suivants la décalent.
    """
    if base_seed is None:
        return None
    return (base_seed + max(attempt - 1, 0)) % _SEED_MODULO
