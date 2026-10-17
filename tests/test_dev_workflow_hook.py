"""Hook UserPromptSubmit `.claude/hooks/dev_workflow.py` : déclenchement sur les demandes de code."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "dev_workflow.py"


def run_hook(stdin: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    full_env = {k: v for k, v in os.environ.items() if k != "DEV_WORKFLOW"}
    full_env.update(env or {})
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=full_env
    )
    assert proc.stderr == "", proc.stderr
    return proc.returncode, proc.stdout


def triggers(prompt: str) -> bool:
    code, out = run_hook(json.dumps({"prompt": prompt}))
    assert code == 0
    if not out.strip():
        return False
    data = json.loads(out)
    assert data["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "feature-dev:feature-dev" in data["hookSpecificOutput"]["additionalContext"]
    assert "code-review" in data["hookSpecificOutput"]["additionalContext"]
    return True


@pytest.mark.parametrize(
    "prompt",
    [
        "Ajoute un bouton de téléchargement sur la page projet",
        "corrige le bug du scheduler",
        "Peux-tu rajouter un champ dans le formulaire ?",
        "fais en sorte que la purge garde les miniatures",
        "feature : export CSV des publications",
        "Add a retry to the TikTok publisher",
        "Please add a retry to the publisher",
        "Ajoute un bouton de téléchargement.\nÇa te va ?",
        "<div> est mal centré, corrige le style",
        "Voici le log :\n" + "x" * 2000 + "\ncorrige ça",
    ],
)
def test_code_requests_trigger(prompt: str) -> None:
    assert triggers(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "liste moi les skills installés",
        "est-ce que le hook marche ?",
        "Où est la route des projets ?",
        "Comment ajouter un bouton ?",
        "Explique comment ajouter une route",
        "le build est lent, une idée ?",
        "lance les tests",
        "git commit les changements",
        "Lance make-video sur ce sujet",
        "le code de la purge est lent",
        "Quel utilisateur a créé ce projet",
        "merci",
        "Voici le log :\n" + "x" * 400 + " corrige " + "x" * 1000,
        "/code-review",
        "! ls",
        "[SYSTEM NOTIFICATION - NOT USER INPUT] changes were pushed",
        "<task-notification>commit review failed</task-notification>",
        "<system-reminder>ajoute ceci</system-reminder>",
        "Stop hook feedback: corrige les fichiers suivants",
        "Another Claude session sent a message:\n<agent-message>ajoute un bouton</agent-message>",
        "[Artifact comment sent to Claude] corrige le titre",
    ],
)
def test_non_requests_stay_silent(prompt: str) -> None:
    assert not triggers(prompt)


@pytest.mark.parametrize("stdin", ["", "not json", "[]", "null", '"ajoute un bouton"', "{}"])
def test_malformed_input_is_silent(stdin: str) -> None:
    assert run_hook(stdin) == (0, "")


def test_env_switch_disables_hook() -> None:
    stdin = json.dumps({"prompt": "ajoute un bouton"})
    assert run_hook(stdin, {"DEV_WORKFLOW": "off"}) == (0, "")
