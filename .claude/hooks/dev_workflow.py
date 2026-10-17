#!/usr/bin/env python3
"""Hook UserPromptSubmit : impose le flux feature-dev → implémentation → code-review.

Quand le prompt de l'utilisateur ressemble à une demande de code (feature, ajout,
modification, correction…), injecte un contexte qui oblige Claude à :
  1. invoquer le skill `feature-dev:feature-dev` avant de coder ;
  2. une fois l'implémentation terminée, invoquer le skill `code-review` sur le diff local.

Ne se déclenche pas pour : une commande slash (`/…`) ou shell (`!…`), un message système
(notification de tâche, retour de hook, message d'agent), une question, ou un prompt sans
verbe d'action de développement. Seuls le début et la fin du prompt sont examinés, pour ne
pas réagir à un log collé au milieu. Choix assumé : un prompt qui commence par une question
(« explique… puis corrige… ») reste silencieux ; la règle de CLAUDE.md s'applique alors.
`DEV_WORKFLOW=off` désactive le hook.
"""
from __future__ import annotations

import json
import os
import re
import sys

# Nombre de caractères examinés au début et à la fin du prompt.
SCAN_CHARS = 400
# Au-delà, ou sur plusieurs lignes, un « ? » final ne suffit plus à classer le prompt en question.
SHORT_QUESTION_CHARS = 200

# Verbes d'action (FR + EN) qui signalent une demande de code ; `feature` / `fonctionnalité`
# sont les seuls noms acceptés seuls, car c'est le critère explicite de l'utilisateur.
CODE_PATTERNS = re.compile(
    r"\b("
    r"r?ajout\w*|cr[ée]e\w*|impl[ée]ment\w*|d[ée]veloppe\w*|coder|codez|code[- ]moi|"
    r"modifi\w*|chang(e|es|er|ez|eons)|corrig\w*|fix\w*|r[ée]par\w*|refacto\w*|"
    r"supprim\w*|retir\w*|renomm\w*|remplac\w*|d[ée]plac\w*|factoris\w*|nettoy\w*|"
    r"r[ée][ée]cri\w*|extrai\w*|migr\w*|int[èe]gr\w*|connecte[rz]?|optimis\w*|am[ée]lior\w*|"
    r"affich\w*|g[èe]re[rz]?|mets|met|utilise[rz]?|fais en sorte|"
    r"feature|fonctionnalit\w*|"
    r"add|create|build|implement|develop|write|update|remove|delete|rename|replace|move|"
    r"make(?!-)|upgrade|refactor|improve|optimi[sz]e|integrate|wire|debug|patch"
    r")\b",
    re.IGNORECASE,
)

# Prompt qui commence par un mot interrogatif ou un impératif d'explication : question.
QUESTION_START = re.compile(
    r"^\s*(est[- ]ce|pourquoi|comment|o[ùu]|combien|qu['’]est|quel\w*|liste|explique|montre|"
    r"dis[- ]moi|c['’]est quoi|je peux|on peut|what|why|how|where|which|who|list|explain|show|"
    r"tell me)\b",
    re.IGNORECASE,
)

# Demande polie (« peux-tu ajouter … ? ») : le « ? » final ne fait pas une question.
REQUEST_START = re.compile(
    r"^\s*(peux[- ]tu|pourrais[- ]tu|tu peux|can you|could you|would you|please)\b",
    re.IGNORECASE,
)

# Messages injectés par le harnais, pas par l'utilisateur.
NON_USER_START = re.compile(
    r"^\s*(<(task-notification|system-reminder|agent-message|cross-session|command-|local-command)|"
    r"\[SYSTEM|Stop hook feedback|Another Claude session|\[Artifact comment)",
    re.IGNORECASE,
)

CONTEXT = (
    "WORKFLOW OBLIGATOIRE (configuré par l'utilisateur dans .claude/settings.json → "
    ".claude/hooks/dev_workflow.py) : ce prompt est une demande de feature ou de code.\n"
    "1. AVANT d'écrire le moindre code, invoque le skill `feature-dev:feature-dev` via l'outil "
    "Skill (args = la demande de l'utilisateur) et suis son flux : exploration du code, "
    "questions de clarification, architecture, puis implémentation.\n"
    "2. UNE FOIS l'implémentation terminée et la garde qualité passée, invoque le skill "
    "`code-review` via l'outil Skill (sans numéro de PR : il relit le diff local) et applique "
    "les corrections justifiées avant de rendre la main.\n"
    "Ne saute aucune des deux étapes, même pour une petite modification. Seule exception : "
    "si le prompt est en réalité une pure question ou une discussion, ignore cette consigne."
)


def is_question(prompt: str) -> bool:
    if QUESTION_START.search(prompt):
        return True
    short_one_liner = len(prompt) <= SHORT_QUESTION_CHARS and "\n" not in prompt
    return short_one_liner and prompt.endswith("?") and not REQUEST_START.search(prompt)


def scan_window(prompt: str) -> str:
    """Début + fin du prompt, pour ignorer un log collé au milieu."""
    if len(prompt) <= 2 * SCAN_CHARS:
        return prompt
    return prompt[:SCAN_CHARS] + "\n" + prompt[-SCAN_CHARS:]


def should_trigger(prompt: str) -> bool:
    prompt = prompt.strip()
    if not prompt or prompt.startswith(("/", "!")) or NON_USER_START.search(prompt):
        return False
    if is_question(prompt):
        return False
    return bool(CODE_PATTERNS.search(scan_window(prompt)))


def main() -> int:
    if os.environ.get("DEV_WORKFLOW", "").lower() in {"off", "0", "false"}:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    if not should_trigger(str(payload.get("prompt") or "")):
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": CONTEXT,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
