"""Exécution isolée des scripts d'animation écrits par Claude.

Un seul point d'entrée, `run_sandboxed()`, qui fait tourner `studio/sandbox_exec.py`
sur un job (script HTML ou Python → images) selon `STUDIO_SANDBOX` :

- `bwrap` (hôte) : bubblewrap, aucun réseau, système en lecture seule, seuls le
  dossier `anim/` (lecture) et le dossier de sortie (écriture) sont visibles,
  environnement vidé (aucune clé API), repo non monté ;
- `container` (Docker, où `unshare` est refusé) : le job est déposé dans
  `STUDIO_SANDBOX_JOBS_DIR`, exécuté par le conteneur `studio-sandbox`
  (`network_mode: none`, sans `.env`) via `studio/sandbox_worker.py` ; les rendus 3D
  (longs) vont dans une file à part (`<jobs>-3d`, conteneur `studio-sandbox-3d`) pour ne
  jamais faire attendre les animations 2D des autres créations ;
- `none` : sans isolation, réservé aux modèles d'animation intégrés (HTML de confiance).

Le mode `auto` (défaut) choisit bwrap s'il fonctionne, sinon `none`.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Literal

from agent.core.env import env_float, env_int

SandboxMode = Literal["bwrap", "container", "none"]
EXEC_SCRIPT = Path(__file__).resolve().parent / "sandbox_exec.py"
DEFAULT_TIMEOUT_S = 300.0
# Rendus 3D (WebGL logiciel, ~3,5 s par image mesurées) : délai proportionnel au nombre d'images avec une marge
# (machine chargée), plafonné sous le délai Bash de Claude Code (30 min quand la 3D est active, launcher.build_env).
SECONDS_PER_FRAME_3D = env_float("STUDIO_3D_SECONDS_PER_FRAME", 6.0)
MAX_3D_TIMEOUT_S = env_float("STUDIO_3D_MAX_TIMEOUT_S", 960.0)
# Attente maximale dans la file du conteneur avant la prise en charge du job (la file est séquentielle).
# File (480 s) + rendu 3D maximal (960 s) + marge + encodage restent sous le délai Bash de 30 min : l'outil rend une
# erreur propre au lieu d'être tué par Claude Code.
QUEUE_WAIT_S = env_float("STUDIO_SANDBOX_QUEUE_WAIT_S", 480.0)
# Marge au-delà du délai du job (démarrage de Chromium, écriture du résultat) avant de l'abandonner.
RESULT_MARGIN_S = 30.0


# Garde-fous ressources (VPS partagé, sans swap) : un rendu Chromium ne doit jamais
# pousser la machine à l'OOM global.
MIN_FREE_MB = env_int("STUDIO_SANDBOX_MIN_FREE_MB", 1200)
MEMORY_WAIT_S = env_float("STUDIO_SANDBOX_MEMORY_WAIT_S", 180.0)
MEMORY_MAX = os.getenv("STUDIO_SANDBOX_MEMORY_MAX", "1G")
CPU_QUOTA = os.getenv("STUDIO_SANDBOX_CPU_QUOTA", "150%")


class SandboxError(RuntimeError):
    pass


def available_memory_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


async def wait_for_memory(min_free_mb: int = MIN_FREE_MB, timeout_s: float = MEMORY_WAIT_S) -> None:
    """Attend que la machine ait assez de mémoire libre avant de lancer Chromium / Python."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        free = available_memory_mb()
        if free is None or free >= min_free_mb:
            return
        if loop.time() > deadline:
            raise SandboxError(
                f"mémoire insuffisante sur la machine ({free} Mo libres, {min_free_mb} Mo requis) : "
                "animation non rendue, réessaie plus tard ou utilise une image"
            )
        await asyncio.sleep(5)


@functools.lru_cache(maxsize=1)
def _cgroup_scope_works() -> bool:
    """`systemd-run --user --scope` : plafonne mémoire/CPU du bac à sable dans son propre cgroup."""
    if shutil.which("systemd-run") is None:
        return False
    try:
        proc = subprocess.run(
            ["systemd-run", "--user", "--scope", "--quiet", "-p", f"MemoryMax={MEMORY_MAX}", "true"],
            capture_output=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _resource_limits() -> list[str]:
    """Préfixe de commande : cgroup plafonné (OOM confiné au bac à sable) + priorité basse."""
    prefix = ["nice", "-n", "10"]
    if _cgroup_scope_works():
        prefix = ["systemd-run", "--user", "--scope", "--quiet",
                  "-p", f"MemoryMax={MEMORY_MAX}", "-p", "MemorySwapMax=0", "-p", f"CPUQuota={CPU_QUOTA}",
                  *prefix]
    return prefix


@functools.lru_cache(maxsize=1)
def _bwrap_works() -> bool:
    if shutil.which("bwrap") is None:
        return False
    try:
        proc = subprocess.run(
            ["bwrap", "--ro-bind", "/", "/", "--unshare-all", "--die-with-parent", "true"],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def sandbox_mode() -> SandboxMode:
    configured = os.getenv("STUDIO_SANDBOX", "auto").strip().lower()
    if configured in ("bwrap", "container", "none"):
        return configured  # type: ignore[return-value]
    return "bwrap" if _bwrap_works() else "none"


def scripts_supported() -> bool:
    """Les scripts écrits par Claude exigent une vraie isolation."""
    return sandbox_mode() in ("bwrap", "container")


def render_timeout(frames: int, *, webgl: bool) -> float:
    """Délai d'un rendu : fixe en 2D, proportionnel au nombre d'images en 3D."""
    if not webgl:
        return DEFAULT_TIMEOUT_S
    return min(MAX_3D_TIMEOUT_S, 60.0 + frames * SECONDS_PER_FRAME_3D)


def jobs_dir(*, webgl: bool = False) -> Path:
    configured = os.getenv("STUDIO_SANDBOX_JOBS_DIR")
    if configured:
        base = Path(configured)
    else:
        from studio.launcher import default_runs_dir

        base = default_runs_dir() / ".sandbox-jobs"
    return base.with_name(f"{base.name}-3d") if webgl else base


def _playwright_browsers() -> Path:
    configured = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
    return Path(configured) if configured else Path.home() / ".cache" / "ms-playwright"


def _bwrap_command(job_file: Path, anim_dir: Path, out_dir: Path) -> list[str]:
    venv = Path(sys.prefix).resolve()
    # L'interpréteur du venv peut passer par des liens symboliques (uv) : on monte chaque étape.
    python_dirs = sorted({str(Path(sys.base_prefix)), str(Path(sys.base_prefix).resolve()),
                          str(Path(os.readlink(venv / "bin" / "python")).parent.parent)
                          if (venv / "bin" / "python").is_symlink() else str(Path(sys.base_prefix))})
    browsers = _playwright_browsers().resolve()
    cmd = [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--symlink", "usr/sbin", "/sbin",
        "--ro-bind", "/etc", "/etc",
        *[arg for d in python_dirs for arg in ("--ro-bind", d, d)],
        "--ro-bind", str(venv), str(venv),
        "--ro-bind", str(EXEC_SCRIPT), "/opt/sandbox/sandbox_exec.py",
        "--ro-bind", str(anim_dir), "/anim",
        "--bind", str(out_dir), "/out",
        "--ro-bind", str(job_file), "/out/job.json",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--tmpfs", "/dev/shm",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--setenv", "HOME", "/tmp",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--chdir", "/out",
    ]
    if browsers.is_dir():
        cmd += ["--ro-bind", str(browsers), str(browsers),
                "--setenv", "PLAYWRIGHT_BROWSERS_PATH", str(browsers)]
    return [*_resource_limits(), *cmd, str(venv / "bin" / "python"), "/opt/sandbox/sandbox_exec.py",
            "/out/job.json"]


async def _run_process(cmd: list[str], timeout_s: float) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise SandboxError(f"délai dépassé ({timeout_s:.0f} s)") from exc
    except BaseException:
        # Annulation : un rendu 3D peut durer un quart d'heure, il ne doit pas survivre à l'outil.
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise
    return proc.returncode or 0, out.decode("utf-8", errors="replace")


async def _run_container(job: dict, timeout_s: float) -> None:
    webgl = bool(job.get("webgl"))
    queue = jobs_dir(webgl=webgl)
    service = "studio-sandbox-3d" if webgl else "studio-sandbox"
    queue.mkdir(parents=True, exist_ok=True)
    queue.chmod(0o777)  # le conteneur sandbox (non-root) y renomme et marque les jobs
    job_id = uuid.uuid4().hex
    tmp = queue / f"{job_id}.tmp"
    tmp.write_text(json.dumps(job), encoding="utf-8")
    tmp.chmod(0o666)
    pending, running = queue / f"{job_id}.json", queue / f"{job_id}.running"
    done, cancel = queue / f"{job_id}.done", queue / f"{job_id}.cancel"
    tmp.rename(pending)  # dépôt atomique : le worker ne lit jamais un job partiel
    loop = asyncio.get_running_loop()
    # Deux délais : la file (séquentielle, partagée) puis le rendu, compté depuis la prise en charge — sinon
    # un job qui attend derrière un long rendu expirerait sans avoir tourné.
    deadline, picked = loop.time() + QUEUE_WAIT_S, False
    try:
        while not done.exists():
            if not picked and running.exists():
                picked, deadline = True, loop.time() + timeout_s + RESULT_MARGIN_S
            if loop.time() > deadline:
                if picked:
                    raise SandboxError(f"délai dépassé ({timeout_s:.0f} s)")
                raise SandboxError(
                    f"le conteneur {service} n'a pas pris le job en {QUEUE_WAIT_S:.0f} s : file occupée par d'autres "
                    f"rendus (réessaie plus tard ou rends ce plan en 2D) ou conteneur arrêté (docker compose up -d {service})"
                )
            await asyncio.sleep(0.5)
    finally:
        if not done.exists():
            # Abandon (délai, outil tué par Claude Code) : un job encore en file est simplement retiré ; un job
            # déjà pris reçoit un `.cancel` pour que le worker arrête le rendu au lieu de le finir pour personne.
            try:
                pending.unlink()
            except FileNotFoundError:
                cancel.touch()
                # Le worker peut déjà l'avoir lu et supprimé : ne jamais masquer l'exception d'origine.
                with contextlib.suppress(OSError):
                    cancel.chmod(0o666)
    done.unlink(missing_ok=True)


async def run_sandboxed(
    kind: Literal["html", "python"],
    script: Path,
    anim_dir: Path,
    out_dir: Path,
    *,
    width: int,
    height: int,
    fps: int,
    duration: float,
    trusted: bool = False,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    webgl: bool = False,
    times: list[float] | None = None,
) -> dict:
    """Rend `script` (dans `anim_dir`) en images dans `out_dir/frames/`. Renvoie le résultat du job.

    `webgl` active la 3D (coupée sinon) ; `times` limite le rendu à ces instants (aperçu).
    """
    mode = sandbox_mode()
    if mode == "none" and not trusted:
        raise SandboxError(
            "aucun bac à sable disponible (bwrap ou conteneur studio-sandbox) : scripts d'animation désactivés"
        )
    await wait_for_memory()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    out_dir.chmod(0o777)  # le conteneur sandbox écrit avec un utilisateur non-root
    params = {"kind": kind, "width": width, "height": height, "fps": fps, "duration": duration,
              "timeout_s": timeout_s, "webgl": webgl, "times": times}

    if mode == "bwrap":
        job_file = out_dir.parent / f".{out_dir.name}.job.json"
        rel_script = script.resolve().relative_to(anim_dir.resolve())
        job_file.write_text(json.dumps({**params, "script": f"/anim/{rel_script}", "root": "/anim", "out_dir": "/out"}),
                            encoding="utf-8")
        try:
            code, output = await _run_process(_bwrap_command(job_file, anim_dir, out_dir), timeout_s + RESULT_MARGIN_S)
        finally:
            job_file.unlink(missing_ok=True)
        if code != 0 and not (out_dir / "result.json").exists():
            raise SandboxError(f"bac à sable bwrap en échec (code {code}) : {output[-1500:]}")
    elif mode == "container":
        await _run_container({**params, "script": str(script.resolve()), "root": str(anim_dir.resolve()),
                              "out_dir": str(out_dir.resolve())}, timeout_s)
    else:
        job_file = out_dir / "job.json"
        job_file.write_text(json.dumps({**params, "script": str(script.resolve()), "root": str(anim_dir.resolve()),
                                        "out_dir": str(out_dir)}),
                            encoding="utf-8")
        code, output = await _run_process([*_resource_limits(), sys.executable, str(EXEC_SCRIPT), str(job_file)],
                                          timeout_s + RESULT_MARGIN_S)
        if code != 0 and not (out_dir / "result.json").exists():
            raise SandboxError(f"rendu en échec (code {code}) : {output[-1500:]}")

    result_path = out_dir / "result.json"
    if not result_path.exists():
        raise SandboxError("le bac à sable n'a produit aucun résultat")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("ok"):
        raise SandboxError(result.get("error") or "échec du rendu de l'animation")
    return result
