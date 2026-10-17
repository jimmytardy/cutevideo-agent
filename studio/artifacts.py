"""Fichiers d'un run Claude Studio exposés au dashboard (détail d'un projet).

Lecture seule du run dir : scénario, voix, rendus, miniatures et critiques par itération.
Seuls `ROOT_MEDIA` et les médias de `ARTIFACT_MEDIA` peuvent être servis (pas le brief, ni les logs).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from studio.contracts import ContractError, resolve_in_run_dir

# Dossier → extensions servables. `voice.wav` est à la racine.
ARTIFACT_MEDIA: dict[str, frozenset[str]] = {
    "renders": frozenset({".mp4"}),
    "thumbnails": frozenset({".png", ".jpg", ".jpeg", ".webp"}),
}
ROOT_MEDIA = frozenset({"voice.wav"})

_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

_RENDER_RE = re.compile(r"^v(\d+)\.mp4$")
_CRITIQUE_RE = re.compile(r"^critique_(\d+)\.json$")
_SCENARIO_CRITIQUE_RE = re.compile(r"^scenario_critique_(\d+)\.json$")


def project_run_dir(project_id: str) -> Path:
    from studio.launcher import default_runs_dir

    return default_runs_dir() / str(project_id)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _media_entry(run_dir: Path, path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": path.relative_to(run_dir).as_posix(), "size": stat.st_size, "mtime": int(stat.st_mtime)}


def list_artifacts(run_dir: Path) -> dict[str, Any]:
    """Résumé du run dir ; `available: False` s'il n'existe plus (purgé ou jamais créé)."""
    if not run_dir.is_dir():
        return {
            "available": False, "scenario": None, "scenario_critiques": [], "voice": None, "thumbnail": None,
            "iterations": {},
        }

    iterations: dict[int, dict[str, Any]] = {}

    def slot(n: int) -> dict[str, Any]:
        return iterations.setdefault(n, {"render": None, "thumbnails": [], "critique": None})

    renders = run_dir / "renders"
    if renders.is_dir():
        for path in sorted(renders.iterdir()):
            match = _RENDER_RE.match(path.name)
            if match and path.is_file():
                slot(int(match.group(1)))["render"] = _media_entry(run_dir, path)

    thumbs = run_dir / "thumbnails"
    thumbnails = [
        _media_entry(run_dir, path)
        for path in (sorted(thumbs.iterdir()) if thumbs.is_dir() else [])
        if path.is_file() and path.suffix.lower() in ARTIFACT_MEDIA["thumbnails"]
    ]

    for path in sorted(run_dir.glob("critique_*.json")):
        match = _CRITIQUE_RE.match(path.name)
        if not match:
            continue
        critique = _read_json(path)
        if isinstance(critique, dict):
            slot(int(match.group(1)))["critique"] = critique

    # Miniature faite une fois après la boucle (thumbnails/final_*) : rattachée à la dernière itération,
    # comme l'AgentRun du miniaturiste (agent/core/claude_studio.py).
    if thumbnails:
        slot(max(iterations) if iterations else 1)["thumbnails"].extend(thumbnails)

    voice = None
    voice_path = run_dir / "voice.wav"
    if voice_path.is_file():
        voice = _media_entry(run_dir, voice_path)
        meta = _read_json(run_dir / "voice.json")
        if isinstance(meta, dict):
            voice.update({k: meta.get(k) for k in ("duration_s", "engine", "voice")})

    # Boucle scénario (avant la voix) : toutes les passes, dans l'ordre.
    scenario_critiques: list[dict[str, Any]] = []
    for path in run_dir.glob("scenario_critique_*.json"):
        match = _SCENARIO_CRITIQUE_RE.match(path.name)
        critique = _read_json(path) if match else None
        if isinstance(critique, dict):
            scenario_critiques.append({**critique, "iteration": int(match.group(1))})
    scenario_critiques.sort(key=lambda c: c["iteration"])

    scenario = _read_json(run_dir / "scenario.json")
    thumbnail = _read_json(run_dir / "thumbnail.json")
    return {
        "available": True,
        "scenario": scenario if isinstance(scenario, dict) else None,
        "scenario_critiques": scenario_critiques,
        "voice": voice,
        "thumbnail": thumbnail if isinstance(thumbnail, dict) else None,
        "iterations": {str(n): iterations[n] for n in sorted(iterations)},
    }


def resolve_artifact_file(run_dir: Path, rel: str) -> tuple[Path, str]:
    """Chemin et type MIME d'un média servable ; `ContractError` sinon."""
    path = resolve_in_run_dir(run_dir, rel)
    parts = path.relative_to(run_dir.resolve()).parts
    if len(parts) == 1:
        allowed = parts[0] in ROOT_MEDIA
    else:
        allowed = len(parts) == 2 and path.suffix.lower() in ARTIFACT_MEDIA.get(parts[0], frozenset())
    if not allowed:
        raise ContractError(f"fichier non exposé : {rel}")
    if not path.is_file():
        raise FileNotFoundError(rel)
    return path, _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
