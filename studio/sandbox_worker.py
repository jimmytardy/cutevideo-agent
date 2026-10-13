"""Service du conteneur `studio-sandbox` : exécute les jobs d'animation déposés par les outils.

    python sandbox_worker.py            # STUDIO_SANDBOX_JOBS_DIR=/var/lib/cutevideo/studio-runs/.sandbox-jobs

Le conteneur n'a ni réseau (`network_mode: none`) ni secrets (pas d'`env_file`) ;
il ne voit que le volume des runs. Protocole : `<id>.json` (job, voir
`studio/sandbox.py`) → exécution de `sandbox_exec.py` → `<out_dir>/result.json`
puis `<id>.done`. Autonome : aucune dépendance au reste du repo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

JOBS_DIR = Path(os.getenv("STUDIO_SANDBOX_JOBS_DIR", "/var/lib/cutevideo/studio-runs/.sandbox-jobs"))
RUNS_ROOT = JOBS_DIR.parent.resolve()
EXEC_SCRIPT = Path(__file__).resolve().parent / "sandbox_exec.py"


def _fail(job: dict, message: str) -> None:
    out = Path(job.get("out_dir", "")).resolve()
    # Jamais d'écriture hors du volume des runs, même pour signaler une erreur.
    if out.is_dir() and out.is_relative_to(RUNS_ROOT):
        (out / "result.json").write_text(json.dumps({"ok": False, "error": message}), encoding="utf-8")


def handle(job_file: Path) -> None:
    running = job_file.with_suffix(".running")
    try:
        job_file.rename(running)  # plusieurs workers possibles : le premier qui renomme prend le job
    except OSError:
        return
    try:
        job = json.loads(running.read_text(encoding="utf-8"))
        out_dir, script = Path(job["out_dir"]).resolve(), Path(job["script"]).resolve()
        # Le job ne peut viser que le volume des runs.
        if not (out_dir.is_relative_to(RUNS_ROOT) and script.is_relative_to(RUNS_ROOT)):
            raise ValueError("chemins hors du volume des runs")
        job_path = out_dir / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        try:
            subprocess.run(
                [sys.executable, str(EXEC_SCRIPT), str(job_path)],
                cwd=str(out_dir), timeout=float(job.get("timeout_s", 300)) + 20,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp",
                     "PLAYWRIGHT_BROWSERS_PATH": os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")},
            )
        except subprocess.TimeoutExpired:
            _fail(job, "délai dépassé")
    except Exception as exc:  # noqa: BLE001 — le job ne doit jamais tuer le service
        try:
            _fail(json.loads(running.read_text(encoding="utf-8")), f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001
            pass
    finally:
        done = running.with_suffix(".done")
        done.touch()
        done.chmod(0o666)
        running.unlink(missing_ok=True)


def main() -> None:
    print(f"studio-sandbox prêt, jobs : {JOBS_DIR}", flush=True)
    while True:
        # Le dossier est créé (0777) par les outils au premier job : le volume appartient à root.
        for job_file in sorted(JOBS_DIR.glob("*.json")) if JOBS_DIR.is_dir() else []:
            print(f"job {job_file.stem}", flush=True)
            handle(job_file)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
