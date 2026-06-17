from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Conversion nombre → lettres via num2words si dispo (dépendance optionnelle).
try:
    from num2words import num2words as _num2words

    _HAS_NUM2WORDS = True
except ImportError:  # pragma: no cover - dépend de l'environnement
    _HAS_NUM2WORDS = False


# Unités / symboles fréquents → forme prononçable française.
UNIT_EXPANSIONS: list[tuple[str, str]] = [
    (r"\bkm/h\b", "kilomètres heure"),
    (r"\bkm²\b", "kilomètres carrés"),
    (r"\bm²\b", "mètres carrés"),
    (r"\bkm\b", "kilomètres"),
    (r"\bcm\b", "centimètres"),
    (r"\bmm\b", "millimètres"),
    (r"\bkg\b", "kilogrammes"),
    (r"\bm/s\b", "mètres par seconde"),
    (r"(\d)\s*%", r"\1 pour cent"),
    (r"(\d)\s*°C", r"\1 degrés"),
    (r"(\d)\s*°", r"\1 degrés"),
    (r"(\d)\s*€", r"\1 euros"),
    (r"(\d)\s*\$", r"\1 dollars"),
    (r"\b&\b", "et"),
]

# Caractères / motifs markdown à retirer (texte non prononçable).
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_CHARS = re.compile(r"[*_`#>~]")

_MAX_WORDS_PER_SENTENCE = 25
# Conjonctions de coordination/subordination où couper une phrase trop longue.
_SPLIT_CONNECTORS = re.compile(r",\s+(et|mais|car|donc|or|puis|tandis que|alors que)\s+")


def _strip_markdown(text: str) -> str:
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _MARKDOWN_CHARS.sub("", text)
    return text


def _expand_units(text: str) -> str:
    for pattern, replacement in UNIT_EXPANSIONS:
        text = re.sub(pattern, replacement, text)
    return text


def _number_to_words(token: str) -> str:
    if not _HAS_NUM2WORDS:
        return token
    try:
        return _num2words(int(token), lang="fr")
    except Exception:  # pragma: no cover - num2words robuste mais on protège
        return token


def _normalize_numbers(text: str) -> str:
    """Convertit les entiers isolés (dont les années) en toutes lettres françaises."""
    if not _HAS_NUM2WORDS:
        return text

    def _replace(match: re.Match[str]) -> str:
        return _number_to_words(match.group(0))

    # Entiers de 1 à 4 chiffres non collés à une lettre (évite « MP3 », « H2O »).
    return re.sub(r"(?<![\w])\d{1,4}(?![\w])", _replace, text)


def _split_long_sentences(text: str, max_words: int = _MAX_WORDS_PER_SENTENCE) -> str:
    """Coupe les phrases trop longues sur une conjonction → deux phrases distinctes."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []
    for sentence in sentences:
        if len(sentence.split()) <= max_words:
            result.append(sentence)
            continue
        # Coupe à la première conjonction : « ..., et ... » → « .... Et ... »
        new_sentence, count = _SPLIT_CONNECTORS.subn(
            lambda m: ". " + m.group(1).capitalize() + " ", sentence, count=1
        )
        result.append(new_sentence)
    return " ".join(result)


def oralize_text(text: str) -> str:
    """Réécrit un texte de narration pour la lecture à voix haute (TTS).

    - retire le markdown résiduel (non prononçable) ;
    - développe unités et symboles (« km/h » → « kilomètres heure », « % » → « pour cent ») ;
    - convertit les nombres isolés en lettres si `num2words` est disponible
      (sinon les chiffres sont conservés, sans erreur) ;
    - découpe les phrases trop longues sur une conjonction.
    """
    if not text or not text.strip():
        return text

    out = _strip_markdown(text)
    out = _expand_units(out)
    out = _normalize_numbers(out)
    out = _split_long_sentences(out)
    # Normalise les espaces multiples introduits par les substitutions.
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out
