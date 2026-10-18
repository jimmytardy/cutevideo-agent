"""Exécuté DANS le bac à sable : transforme un script d'animation en images.

    python sandbox_exec.py <job.json>

Autonome (aucun import de `agent.*` / `studio.*`, aucun secret) : il tourne sous
bwrap sur l'hôte ou dans le conteneur `studio-sandbox` (sans réseau). Le job
décrit : `kind` (html | python), `script` (chemin absolu), `out_dir`, `width`,
`height`, `fps`, `duration`. Les images sont écrites dans `<out_dir>/frames/`.
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import subprocess
import sys
from pathlib import Path

PYTHON_MEMORY_LIMIT = 2 * 1024**3

# Avance les animations CSS / Web Animations à l'instant t (relatif à leur apparition) :
# elles tournent sinon sur l'horloge réelle du compositeur, pas sur l'horloge simulée.
_SEEK_JS = """
(t) => {
  for (const a of document.getAnimations()) {
    if (a.__born === undefined) { a.__born = t; a.pause(); }
    a.currentTime = (t - a.__born) * 1000;
  }
}
"""


async def render_html(job: dict, frames: Path) -> int:
    from playwright.async_api import async_playwright

    fps, n = int(job["fps"]), max(1, round(float(job["duration"]) * int(job["fps"])))
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=[
            # Défense en profondeur : le bac à sable n'a déjà pas de réseau.
            "--host-resolver-rules=MAP * ~NOTFOUND",
            "--proxy-server=http://127.0.0.1:9",
            "--disable-gpu",
            "--font-render-hinting=none",
            # Empreinte mémoire minimale : un seul renderer, tas JS borné, pas d'extras.
            "--renderer-process-limit=1",
            "--js-flags=--max-old-space-size=384",
            "--disable-extensions",
            "--disable-background-networking",
            "--mute-audio",
        ])
        try:
            page = await browser.new_page(viewport={"width": int(job["width"]), "height": int(job["height"])})
            await page.route("**/*", lambda route: route.continue_() if route.request.url.startswith("file:")
                             else route.abort())
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            # Horloge simulée figée : le temps n'avance que frame par frame (sinon il s'écoule
            # en temps réel pendant le chargement et les captures, et l'animation « saute »).
            await page.clock.install(time=0)
            await page.clock.pause_at(1)
            await page.goto(Path(job["script"]).as_uri(), wait_until="load")
            await page.evaluate("document.fonts ? document.fonts.ready : null")
            if errors:
                raise RuntimeError(f"erreur JavaScript : {errors[0]}")
            has_render = await page.evaluate("typeof window.renderFrame === 'function'")
            if not has_render:
                await page.evaluate("window.gsap && window.gsap.ticker.lagSmoothing(0)")
            elapsed_ms = 0
            has_check = await page.evaluate("typeof window.__studioCheck === 'function'")
            seen: dict[str, str] = {}
            check_every = max(1, fps // 2)
            for i in range(n):
                t = i / fps
                if has_render:
                    await page.evaluate("async (t) => { await window.renderFrame(t); }", t)
                else:
                    target_ms = round(t * 1000)
                    if target_ms > elapsed_ms:
                        await page.clock.run_for(target_ms - elapsed_ms)
                        elapsed_ms = target_ms
                    await page.evaluate(_SEEK_JS, t)
                await page.screenshot(path=str(frames / f"frame_{i:05d}.jpg"), type="jpeg", quality=94)
                # Contrôle des zones toutes les ~0,5 s (un zoom caméra peut sortir le contenu en cours de route).
                if has_check and (i % check_every == 0 or i == n - 1):
                    for w in await page.evaluate("window.__studioCheck()") or []:
                        key = "".join(c for c in str(w) if not c.isdigit())
                        seen.setdefault(key, f"t={t:.1f}s : {w}")
                if errors:
                    raise RuntimeError(f"erreur JavaScript à t={t:.2f}s : {errors[0]}")
        finally:
            await browser.close()
    # Alertes du kit studio.js (éléments hors des zones utiles, scène vide…), première occurrence de chacune.
    job["_warnings"] = list(seen.values())[:12]
    return n


def _limit_memory() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (PYTHON_MEMORY_LIMIT, PYTHON_MEMORY_LIMIT))
    os.nice(5)


def render_python(job: dict, frames: Path) -> int:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": "/tmp",
        "OUT_DIR": str(frames),
        "WIDTH": str(job["width"]),
        "HEIGHT": str(job["height"]),
        "FPS": str(job["fps"]),
        "DURATION": str(job["duration"]),
    }
    proc = subprocess.run(
        [sys.executable, job["script"]], cwd=str(frames), env=env,
        capture_output=True, text=True, timeout=float(job.get("timeout_s", 240)),
        preexec_fn=_limit_memory,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"le script Python a échoué (code {proc.returncode}) : {proc.stderr[-1500:]}")
    count = len([p for p in frames.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
    if not count:
        raise RuntimeError("le script n'a écrit aucune image frame_00000.png… dans OUT_DIR")
    return count


def main(job_path: str) -> int:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    frames = Path(job["out_dir"]) / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    result_path = Path(job["out_dir"]) / "result.json"
    try:
        if job["kind"] == "html":
            count = asyncio.run(render_html(job, frames))
        elif job["kind"] == "python":
            count = render_python(job, frames)
        else:
            raise ValueError(f"type de script inconnu : {job['kind']}")
        result = {"ok": True, "frames": count, "warnings": job.get("_warnings", [])}
    except subprocess.TimeoutExpired:
        result = {"ok": False, "error": f"délai dépassé ({job.get('timeout_s', 240)} s)"}
    except Exception as exc:  # noqa: BLE001 — renvoyé tel quel à Claude
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:2000]}
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
