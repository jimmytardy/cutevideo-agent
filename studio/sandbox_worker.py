"""Service du conteneur `studio-sandbox` : exécute les jobs d'animation déposés par les outils.

    python sandbox_worker.py            # STUDIO_SANDBOX_JOBS_DIR=/var/lib/cutevideo/studio-runs/.sandbox-jobs

Le conteneur n'a ni réseau (`network_mode: none`) ni secrets (pas d'`env_file`) ;
il ne voit que le volume des runs. Protocole : `<id>.json` (job, voir
`studio/sandbox.py`) → `<id>.running` → exécution de `sandbox_exec.py` →
`<out_dir>/result.json` puis `<id>.done`. Un `<id>.cancel` déposé par l'outil (délai
dépassé, outil tué) arrête le rendu. Le conteneur `studio-sandbox-3d` lance le même
service sur la file 3D. Autonome : aucune dépendance au reste du repo.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

JOBS_DIR = Path(os.getenv("STUDIO_SANDBOX_JOBS_DIR", "/var/lib/cutevideo/studio-runs/.sandbox-jobs"))
RUNS_ROOT = JOBS_DIR.parent.resolve()
EXEC_SCRIPT = Path(__file__).resolve().parent / "sandbox_exec.py"
POLL_S = 0.5
# Marge sur le délai du job : le worker doit abandonner AVANT le producteur (studio/sandbox.py, RESULT_MARGIN_S = 30).
KILL_MARGIN_S = 20
# Marqueurs laissés par une course producteur/worker (abandon pile à la fin du rendu) : balayés après ce délai.
STALE_MARKER_S = 3600


def _fail(job: dict, message: str) -> None:
    out = Path(job.get("out_dir", "")).resolve()
    # Jamais d'écriture hors du volume des runs, même pour signaler une erreur.
    if out.is_dir() and out.is_relative_to(RUNS_ROOT):
        (out / "result.json").write_text(json.dumps({"ok": False, "error": message}), encoding="utf-8")


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def handle(job_file: Path) -> None:
    running, cancel = job_file.with_suffix(".running"), job_file.with_suffix(".cancel")
    try:
        job_file.rename(running)  # plusieurs workers possibles : le premier qui renomme prend le job
    except OSError:
        return
    try:
        if cancel.exists():
            return
        job = json.loads(running.read_text(encoding="utf-8"))
        out_dir, script = Path(job["out_dir"]).resolve(), Path(job["script"]).resolve()
        root = Path(job.get("root") or script.parent).resolve()  # dossier servi aux scènes 3D (sandbox_exec)
        # Le job ne peut viser que le volume des runs.
        if not all(p.is_relative_to(RUNS_ROOT) for p in (out_dir, script, root)):
            raise ValueError("chemins hors du volume des runs")
        job_path = out_dir / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        # Groupe de processus dédié : à l'expiration, Chromium et ses renderers meurent avec le script, au lieu
        # de survivre orphelins (zombies comptés dans pids_limit).
        proc = subprocess.Popen(
            [sys.executable, str(EXEC_SCRIPT), str(job_path)],
            cwd=str(out_dir), start_new_session=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp",
                 "PLAYWRIGHT_BROWSERS_PATH": os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")},
        )
        deadline = time.monotonic() + float(job.get("timeout_s", 300)) + KILL_MARGIN_S
        while proc.poll() is None:
            if cancel.exists():
                _kill_group(proc)
                _fail(job, "rendu annulé par l'outil")
                break
            if time.monotonic() > deadline:
                _kill_group(proc)
                _fail(job, "délai dépassé")
                break
            time.sleep(POLL_S)
    except Exception as exc:  # noqa: BLE001 — le job ne doit jamais tuer le service
        try:
            _fail(json.loads(running.read_text(encoding="utf-8")), f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001
            pass
    finally:
        running.unlink(missing_ok=True)
        if cancel.exists():
            cancel.unlink(missing_ok=True)  # l'outil est parti : personne n'attend le `.done`
        else:
            done = running.with_suffix(".done")
            done.touch()
            done.chmod(0o666)


def sweep_stale_markers(now: float | None = None) -> None:
    """Supprime les `.cancel` / `.done` orphelins (producteur parti, ou annulation arrivée après la fin)."""
    now = time.time() if now is None else now
    for marker in [*JOBS_DIR.glob("*.cancel"), *JOBS_DIR.glob("*.done")]:
        try:
            if now - marker.stat().st_mtime > STALE_MARKER_S and not marker.with_suffix(".running").exists():
                marker.unlink()
        except OSError:
            pass


def main() -> None:
    print(f"studio-sandbox prêt, jobs : {JOBS_DIR}", flush=True)
    last_sweep = 0.0
    while True:
        if JOBS_DIR.is_dir() and time.monotonic() - last_sweep > 600:
            sweep_stale_markers()
            last_sweep = time.monotonic()
        # Le dossier est créé (0777) par les outils au premier job : le volume appartient à root.
        for job_file in sorted(JOBS_DIR.glob("*.json")) if JOBS_DIR.is_dir() else []:
            print(f"job {job_file.stem}", flush=True)
            handle(job_file)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
