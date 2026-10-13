"""Recalage des mots Whisper sur le texte exact du script.

Whisper ne sert qu'aux timestamps : l'orthographe affichée en sous-titres
doit être celle du script (« flamant », pas « flamand »).
"""

from __future__ import annotations

import difflib
import re
import unicodedata

_TOKEN = re.compile(r"\S+")


def _norm(word: str) -> str:
    text = unicodedata.normalize("NFKD", word.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text)


def align_words(words: list[dict], script: str) -> list[dict]:
    """Remplace le texte des mots Whisper par les mots du script, en gardant les timings."""
    script_words = _TOKEN.findall(script)
    if not words or not script_words:
        return words
    matcher = difflib.SequenceMatcher(
        a=[_norm(w["word"]) for w in words], b=[_norm(w) for w in script_words], autojunk=False
    )
    aligned: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                aligned.append({**words[i1 + k], "word": script_words[j1 + k]})
        elif tag == "replace":
            # Nombre de mots différent : on répartit les mots du script sur la plage temporelle.
            start, end = words[i1]["start"], words[i2 - 1]["end"]
            n = j2 - j1
            step = (end - start) / n
            for k in range(n):
                aligned.append({
                    "word": script_words[j1 + k],
                    "start": round(start + k * step, 3),
                    "end": round(start + (k + 1) * step, 3),
                })
        elif tag == "insert" and aligned:
            # Mots du script non reconnus : rattachés au mot précédent.
            aligned[-1] = {**aligned[-1], "word": " ".join([aligned[-1]["word"], *script_words[j1:j2]])}
        # "delete" : mot entendu absent du script (hésitation, artefact) → ignoré.
    return aligned
