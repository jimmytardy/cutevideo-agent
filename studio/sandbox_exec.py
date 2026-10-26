"""Exécuté DANS le bac à sable : transforme un script d'animation en images.

    python sandbox_exec.py <job.json>

Autonome (aucun import de `agent.*` / `studio.*`, aucun secret) : il tourne sous
bwrap sur l'hôte ou dans le conteneur `studio-sandbox` (sans réseau). Le job
décrit : `kind` (html | python), `script` (chemin absolu), `out_dir`, `width`,
`height`, `fps`, `duration`, `timeout_s`, et pour le HTML `webgl` (3D, coupé sinon), `root`
(dossier anim/) et `times` (aperçu : seulement ces instants). Les images sont écrites dans
`<out_dir>/frames/`.
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

PYTHON_MEMORY_LIMIT = 2 * 1024**3
# Frames mesurées avant de projeter la durée totale d'un rendu (abandon précoce s'il dépasse le délai).
PROBE_FRAMES = 5
# WebGL n'existe que pour les rendus 3D (`animate --3d`, modèles 3D) : SwiftShader, rendu logiciel sur CPU.
# Partout ailleurs il est coupé, c'est ce qui réserve la 3D aux chaînes qui y ont droit.
WEBGL_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--js-flags=--max-old-space-size=768"]
# --disable-webgl seul laisse WebGL ouvert via OffscreenCanvas : sans rasteriseur logiciel (SwiftShader), aucun
# contexte 3D ne peut plus être créé ; le canvas 2D et le SVG, rendus par Skia sur CPU, ne sont pas touchés.
# Les scènes 3D sont servies sous cette origine fictive, depuis le seul dossier anim/ : une image chargée en file://
# « salit » le canvas, que WebGL refuse alors comme texture (icônes du kit). Rien d'autre n'est servi.
ANIM_ORIGIN = "http://anim.studio/"
NO_WEBGL_ARGS = ["--disable-webgl", "--disable-3d-apis", "--disable-software-rasterizer",
                 "--js-flags=--max-old-space-size=384"]

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

    fps = int(job["fps"])
    times = job.get("times") or [i / fps for i in range(max(1, round(float(job["duration"]) * fps)))]
    n, timeout_s = len(times), float(job.get("timeout_s", 300))
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=[
            # Défense en profondeur : le bac à sable n'a déjà pas de réseau.
            "--host-resolver-rules=MAP * ~NOTFOUND",
            "--proxy-server=http://127.0.0.1:9",
            "--disable-gpu",
            "--font-render-hinting=none",
            # Empreinte mémoire minimale : un seul renderer, tas JS borné, pas d'extras.
            "--renderer-process-limit=1",
            *(WEBGL_ARGS if job.get("webgl") else NO_WEBGL_ARGS),
            "--disable-extensions",
            "--disable-background-networking",
            "--mute-audio",
        ])
        try:
            page = await browser.new_page(viewport={"width": int(job["width"]), "height": int(job["height"])})
            # Lu par les kits (studio3d.js) : format et cadence du rendu, sans horloge réelle.
            await page.add_init_script(
                f"window.__studioJob = {json.dumps({'fps': fps, 'width': job['width'], 'height': job['height']})};"
            )
            script = Path(job["script"])
            if job.get("webgl"):
                root = Path(job.get("root") or script.parent).resolve()

                async def serve(route) -> None:
                    url = route.request.url
                    if not url.startswith(ANIM_ORIGIN):
                        await route.abort()
                        return
                    target = (root / unquote(urlparse(url).path).lstrip("/")).resolve()
                    if target.is_relative_to(root) and target.is_file():
                        await route.fulfill(path=str(target))
                    else:
                        await route.fulfill(status=404, body="")

                await page.route("**/*", serve)
                page_url = ANIM_ORIGIN + script.resolve().relative_to(root).as_posix()
            else:
                await page.route("**/*", lambda route: route.continue_() if route.request.url.startswith("file:")
                                 else route.abort())
                page_url = script.as_uri()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            # Horloge simulée figée : le temps n'avance que frame par frame (sinon il s'écoule
            # en temps réel pendant le chargement et les captures, et l'animation « saute »).
            await page.clock.install(time=0)
            await page.clock.pause_at(1)
            await page.goto(page_url, wait_until="load")
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
            started = time.monotonic()
            for i, t in enumerate(times):
                # La 1re image paie la compilation des shaders et le chargement des textures : mesure à partir de la 2e.
                if i == 1:
                    started = time.monotonic()
                if i == PROBE_FRAMES + 1 and n > 2 * PROBE_FRAMES:
                    per_frame = (time.monotonic() - started) / PROBE_FRAMES
                    if per_frame * n > timeout_s:
                        raise RuntimeError(
                            f"rendu trop lent : {per_frame:.1f} s/image × {n} images ≈ {per_frame * n / 60:.0f} min "
                            f"> délai {timeout_s / 60:.0f} min — raccourcis l'animation ou allège la scène "
                            "(quality, dof, ombres)"
                        )
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
