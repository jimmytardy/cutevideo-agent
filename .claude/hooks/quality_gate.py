#!/usr/bin/env python3
"""Garde qualité (hook Stop de Claude Code) : à chaque fin de tour qui a modifié du code.

1. Vérifications automatiques sur les fichiers touchés depuis le dernier passage :
   ruff (Python), vulture (code mort Python, baseline `.vulture_whitelist.py`),
   tsc + ESLint + knip (code mort TS) si le dashboard est touché.
   En cas d'échec, le tour est bloqué : Claude doit corriger avant de rendre la main.
2. Si tout passe, une fois par tour : demande une revue (logique, code dupliqué, code mort,
   maintenance) par le sous-agent `code-quality-reviewer` sur ces fichiers.

État (empreintes des fichiers déjà vérifiés) dans `.git/quality_gate_state.json`, jamais commité.
Désactivation ponctuelle : `QUALITY_GATE=off`.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".git" / "quality_gate_state.json"
PY_DIRS = ("agent", "api", "studio", "scripts", "tests")
CODE_EXT = (".py", ".ts", ".tsx")
EXCLUDE = ("graphify-out/", "node_modules/", ".next/", "studio/workspace/anim/lib/")
# Types vulture retenus (les « unused variable/attribute » = champs Pydantic/SQLAlchemy, trop bruyants).
VULTURE_KINDS = ("unused function", "unused method", "unused class", "unused import",
                 "unused property", "unreachable code", "redundant if")
VULTURE_IGNORE_DECORATORS = "@router.*,@app.*,@*.validator,@model_validator,@field_validator,@pytest.*"
MAX_OUTPUT = 4000


def run(cmd: list[str], cwd: Path = ROOT, timeout: int = 240) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 0, f"(outil absent, ignoré : {cmd[0]})"
    except subprocess.TimeoutExpired:
        return 1, f"(délai dépassé : {' '.join(cmd[:3])})"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def changed_code_files() -> list[str]:
    _, tracked = run(["git", "diff", "--name-only", "HEAD"])
    _, untracked = run(["git", "ls-files", "--others", "--exclude-standard"])
    files = {f for f in (tracked + "\n" + untracked).splitlines() if f}
    return sorted(
        f for f in files
        if f.endswith(CODE_EXT) and not any(x in f for x in EXCLUDE) and (ROOT / f).is_file()
    )


def digest(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1))


def check_python(files: list[str]) -> list[str]:
    errors = []
    code, out = run(["uvx", "ruff", "check", *files])
    if code:
        errors.append(f"ruff :\n{out}")
    code, out = run([
        "uvx", "vulture", *PY_DIRS, ".vulture_whitelist.py", "--min-confidence", "60",
        "--exclude", "*/workspace/*,*/alembic/*", "--ignore-decorators", VULTURE_IGNORE_DECORATORS,
    ])
    dead = [line for line in out.splitlines()
            if line.split(":", 1)[0] in files and any(k in line for k in VULTURE_KINDS)]
    if dead:
        errors.append("vulture (code mort ; si faux positif, l'ajouter à .vulture_whitelist.py) :\n" + "\n".join(dead))
    return errors


def check_dashboard(files: list[str]) -> list[str]:
    dash = ROOT / "dashboard"
    rel = [f.removeprefix("dashboard/") for f in files]
    errors = []
    code, out = run(["npx", "tsc", "--noEmit"], cwd=dash)
    if code:
        errors.append(f"tsc :\n{out}")
    code, out = run(["npx", "eslint", "--max-warnings", "0", *rel], cwd=dash)
    if code:
        errors.append(f"eslint :\n{out}")
    # knip (baseline à zéro) : fichiers jamais importés, exports/types non importés ailleurs.
    _, out = run(["npx", "--yes", "knip@5", "--include", "files,exports,types", "--no-progress",
                  "--no-exit-code"], cwd=dash)
    findings = [line.strip() for line in out.splitlines()
                if line.strip() and not line.startswith("Unused") and any(r in line for r in rel)]
    if findings:
        errors.append("knip — code TS mort (supprimer, ou retirer `export` si utilisé seulement dans le fichier) :\n"
                      + "\n".join(findings))
    return errors


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


def main() -> None:
    if os.environ.get("QUALITY_GATE") == "off":
        sys.exit(0)
    try:
        hook_input = json.load(sys.stdin)
    except ValueError:
        hook_input = {}
    continuing = bool(hook_input.get("stop_hook_active"))

    state = load_state()
    if not continuing:
        state["review_requested"] = False
    known = state.setdefault("files", {})
    touched = [f for f in changed_code_files() if known.get(f) != digest(f)]
    if not touched:
        save_state(state)
        sys.exit(0)

    py = [f for f in touched if f.endswith(".py")]
    ts = [f for f in touched if f.startswith("dashboard/") and f.endswith((".ts", ".tsx"))]
    errors = check_python(py) if py else []
    if ts:
        errors += check_dashboard(ts)

    fingerprint = hashlib.sha256("".join(digest(f) for f in touched).encode()).hexdigest()
    if errors:
        if continuing and state.get("last_failure") == fingerprint:
            # Rien n'a changé depuis le dernier blocage : on rend la main plutôt que boucler.
            save_state(state)
            emit({"systemMessage": "Garde qualité : échecs non corrigés, voir le dernier rapport."})
        state["last_failure"] = fingerprint
        save_state(state)
        report = "\n\n".join(errors)[:MAX_OUTPUT]
        emit({"decision": "block",
              "reason": f"Garde qualité — corrige ces problèmes avant de terminer :\n\n{report}"})

    state.pop("last_failure", None)
    for f in touched:
        known[f] = digest(f)
    if state.get("review_requested"):
        save_state(state)  # corrections issues de la revue de ce tour : pas de seconde revue
        sys.exit(0)
    state["review_requested"] = True
    save_state(state)
    reason = (
        "Garde qualité : ruff / vulture / tsc / eslint OK. Lance maintenant l'agent `code-quality-reviewer` "
        "(outil Agent, subagent_type \"code-quality-reviewer\" ; s'il n'est pas encore chargé dans la session : "
        "general-purpose avec les consignes de .claude/agents/code-quality-reviewer.md) sur ces fichiers modifiés, "
        "puis applique ses "
        "corrections justifiées (logique, code dupliqué, code mort, maintenabilité) et relance les tests "
        "concernés :\n" + "\n".join(f"- {f}" for f in touched)
    )
    emit({"decision": "block", "reason": reason})


if __name__ == "__main__":
    main()
