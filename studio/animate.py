"""Animations des Shorts : modèles intégrés et scripts jetables écrits par Claude.

Le niveau autorisé vient de `STUDIO_ANIMATIONS` (posé par le launcher depuis le
brief, hors de portée de Claude) : `off` | `templates` | `scripts`. Les images
sont produites dans le bac à sable (`studio/sandbox.py`) puis encodées ici en un
clip 1080×1920 sans audio, utilisable tel quel comme `clip.media` d'une timeline.

La 3D (modèles `*3d`, `animate --3d`) n'existe que si `STUDIO_MOTION3D=1` : WebGL
activé, délai proportionnel au nombre d'images, file du conteneur 3D. C'est la
ressource réservée aux abonnements qui y ont droit ; ailleurs WebGL est coupé.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from agent.core.env import env_float
from agent.skills.video.ffmpeg_runtime import filter_thread_args, run_ffmpeg, thread_args
from studio.assets import SHORT_FPS, SHORT_HEIGHT, SHORT_WIDTH, WORKSPACE_LIB
from studio.contracts import ContractError, read_json, resolve_in_run_dir, write_json
from studio.media import extract_frames, record_credit, sheet_from_images
from studio.sandbox import SandboxError, render_timeout, run_sandboxed, scripts_supported

AnimationPolicy = Literal["off", "templates", "scripts"]
ANIMATION_POLICIES: tuple[AnimationPolicy, ...] = ("off", "templates", "scripts")
TEMPLATES_DIR = Path(__file__).resolve().parent / "anim_templates"
TEMPLATES_2D = ("title", "counter", "bars", "list", "compare", "steps", "map", "before_after", "paradox")
TEMPLATES_3D = ("phone3d", "number3d")
TEMPLATES = TEMPLATES_2D + TEMPLATES_3D
MAX_DURATION_S = 12.0
# Un plan 3D coûte ~3 s de rendu par image (1080×1920, CPU) : 7 s ≈ 210 images ≈ 11 min.
MAX_3D_DURATION_S = env_float("STUDIO_3D_MAX_CLIP_S", 7.0)
# Garde-fou de temps par vidéo : total des plans 3D distincts (un nouveau rendu du même nom remplace l'ancien).
# Le fichier vit dans le run dir que Claude peut modifier : il borne la dérive, pas un abus (la file 3D séparée
# protège les autres créations).
MOTION3D_BUDGET_S = env_float("STUDIO_MOTION3D_MAX_S", 20.0)
MOTION3D_LEDGER = Path("anim") / ".motion3d.json"
PREVIEW_FRAMES = 6
# Mesuré dans studio-sandbox-3d (1080×1920, 1,5 CPU, ombres + reflet + halo + profondeur de champ) : sert à
# annoncer la durée d'un rendu complet après l'aperçu (le délai du job garde une marge, voir sandbox.py).
EXPECTED_SECONDS_PER_FRAME_3D = 3.5
SCRIPT_KINDS = {".html": "html", ".htm": "html", ".py": "python"}


def animation_policy() -> AnimationPolicy:
    value = os.getenv("STUDIO_ANIMATIONS", "scripts").strip().lower()
    return value if value in ANIMATION_POLICIES else "off"  # type: ignore[return-value]


def _require(level: AnimationPolicy) -> None:
    policy = animation_policy()
    if ANIMATION_POLICIES.index(policy) < ANIMATION_POLICIES.index(level):
        allowed = {"off": "aucune animation", "templates": "uniquement animate-template"}[policy]
        raise ContractError(f"animations non autorisées pour cette chaîne ({policy} : {allowed})")


def motion3d_allowed() -> bool:
    return os.getenv("STUDIO_MOTION3D") == "1"


def _require_3d() -> None:
    if not motion3d_allowed():
        raise ContractError("3D non disponible pour cette chaîne (style motion design 3D et abonnement requis)")


def _available_templates() -> tuple[str, ...]:
    return TEMPLATES if motion3d_allowed() else TEMPLATES_2D


def _ledger(run_dir: Path) -> dict[str, float]:
    try:
        data = read_json(run_dir / MOTION3D_LEDGER, {})
        return {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (ValueError, TypeError, AttributeError):
        return {}  # fichier abîmé (le run dir est modifiable par Claude) : on repart de zéro


@contextmanager
def _ledger_lock(run_dir: Path) -> Iterator[None]:
    """Sérialise « vérifier le budget → réserver » entre les processus `studio.tools` lancés dans le même tour."""
    lock = run_dir / MOTION3D_LEDGER.with_suffix(".lock")
    with lock.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


@contextmanager
def _motion3d_reservation(run_dir: Path, name: str, duration: float, active: bool) -> Iterator[None]:
    """Réserve la durée d'un plan 3D avant son rendu, et la rend si le rendu échoue."""
    if not active:
        yield
        return
    with _ledger_lock(run_dir):
        ledger = _ledger(run_dir)
        used = sum(v for k, v in ledger.items() if k != name)
        if used + duration > MOTION3D_BUDGET_S + 0.01:
            raise ContractError(
                f"budget 3D de la vidéo dépassé : {used:.1f} s déjà rendues + {duration:.1f} s > "
                f"{MOTION3D_BUDGET_S:.0f} s (réserve la 3D aux plans clés, le reste avec le kit 2D ; relancer un "
                "plan existant sous le même --name le remplace)"
            )
        previous = ledger.get(name)
        ledger[name] = round(duration, 2)
        write_json(run_dir / MOTION3D_LEDGER, ledger)
    try:
        yield
    except BaseException:
        with _ledger_lock(run_dir):
            ledger = _ledger(run_dir)
            if previous is None:
                ledger.pop(name, None)
            else:
                ledger[name] = previous
            write_json(run_dir / MOTION3D_LEDGER, ledger)
        raise


def _check_3d_duration(duration: float) -> None:
    if duration > MAX_3D_DURATION_S:
        raise ContractError(f"--duration ≤ {MAX_3D_DURATION_S:.0f} s pour un plan 3D (rendu ~3,5 s par image)")


def _forget_3d(run_dir: Path, name: str) -> None:
    """Un plan rendu en 2D sous un nom qui était 3D ne compte plus dans le budget 3D."""
    with _ledger_lock(run_dir):
        ledger = _ledger(run_dir)
        if ledger.pop(name, None) is not None:
            write_json(run_dir / MOTION3D_LEDGER, ledger)


def _check_name(name: str) -> str:
    if not name or not all(c.isalnum() or c in "_-" for c in name):
        raise ContractError(f"--name invalide : {name!r} (lettres, chiffres, _ et - seulement)")
    return name


def _check_duration(duration: float) -> float:
    if not 0.5 <= duration <= MAX_DURATION_S:
        raise ContractError(f"--duration entre 0.5 et {MAX_DURATION_S:.0f} s")
    return duration


async def _encode(frames_dir: Path, fps: int, duration: float, out: Path) -> None:
    first = sorted(p for p in frames_dir.iterdir() if p.name.startswith("frame_"))
    if not first:
        raise ContractError("aucune image frame_00000.(png|jpg) produite")
    ext = first[0].suffix
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={SHORT_WIDTH}:{SHORT_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={SHORT_WIDTH}:{SHORT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={SHORT_FPS},format=yuv420p,tpad=stop_mode=clone:stop_duration={duration:.2f}"
    )
    await run_ffmpeg([
        "ffmpeg", "-y",
        *filter_thread_args(),
        "-framerate", str(fps), "-i", str(frames_dir / f"frame_%05d{ext}"),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        *thread_args(),
        "-c:v", "libx264", "-crf", "17", "-preset", "veryfast", "-an",
        str(out),
    ], error_prefix=f"Encodage animation {out.name}")


async def _finish(
    run_dir: Path, name: str, work: Path, fps: int, duration: float, credit: dict, warnings: list[str] | None = None
) -> dict[str, Any]:
    out = run_dir / "media" / f"anim_{name}.mp4"
    # Écriture atomique : la reprise réutilise les animations déjà présentes dans `media/` et
    # `render._validate_inputs()` ne revérifie que les images, donc un .mp4 tronqué par une mise à mort du
    # groupe de processus — devenue un cas de routine avec le watchdog — serait réutilisé tel quel.
    tmp_out = work / f"anim_{name}.tmp.mp4"
    await _encode(work / "frames", fps, duration, tmp_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out.replace(out)
    rel = str(out.relative_to(run_dir))
    record_credit(run_dir, rel, {
        "source": "animation", "license": "original", "author": "Claude Studio",
        "attribution": None, "source_url": None, "requires_attribution": False, **credit,
    })
    review = await extract_frames(run_dir, out, max(duration / 6, 0.4), run_dir / "review" / f"anim_{name}",
                                  guides=True)
    shutil.rmtree(work / "frames", ignore_errors=True)
    result: dict[str, Any] = {"media": rel, "duration_s": duration, "sheet": review["sheet"]}
    if warnings:
        result["zone_warnings"] = warnings
        result["hint"] = "corrige positions et tailles (contenu entre y 170 et 1180, x 60 et 960, éléments grands) puis relance"
    return result


async def _preview(
    run_dir: Path, name: str, work: Path, times: list[float], three_d: bool, duration: float,
    warnings: list[str] | None,
) -> dict[str, Any]:
    """Aperçu : quelques instants rendus en planche (`review/anim_<name>/preview.png`), sans vidéo."""
    frames = sorted((work / "frames").glob("frame_*"))
    if len(frames) != len(times):
        raise ContractError(f"aperçu incomplet : {len(frames)} images sur {len(times)}")
    sheet = run_dir / "review" / f"anim_{name}" / "preview.png"
    await sheet_from_images([(f, f"{t:.1f}s") for f, t in zip(frames, times, strict=True)], sheet)
    shutil.rmtree(work / "frames", ignore_errors=True)
    result: dict[str, Any] = {"preview": str(sheet.relative_to(run_dir)), "frames": len(frames)}
    if three_d:
        result["estimated_render_min"] = round(duration * SHORT_FPS * EXPECTED_SECONDS_PER_FRAME_3D / 60, 1)
    if warnings:
        result["zone_warnings"] = warnings
    return result


def _render_plan(duration: float, three_d: bool, preview: bool) -> tuple[list[float] | None, float]:
    """Instants à rendre (aperçu) et délai du job."""
    frames = max(1, round(duration * SHORT_FPS))
    if preview:
        times = [round(min(duration - 1 / SHORT_FPS, k * duration / (PREVIEW_FRAMES - 1)), 3) for k in range(PREVIEW_FRAMES)]
        return times, render_timeout(PREVIEW_FRAMES, webgl=three_d)
    return None, render_timeout(frames, webgl=three_d)


async def animate_template(
    run_dir: Path, template: str, params: dict, duration: float, name: str, *, preview: bool = False
) -> dict[str, Any]:
    _require("templates")
    if template not in _available_templates():
        raise ContractError(f"modèle inconnu : {template} (disponibles : {', '.join(_available_templates())})")
    three_d = template in TEMPLATES_3D
    name, duration = _check_name(name), _check_duration(duration)
    if three_d:
        _check_3d_duration(duration)
    with _motion3d_reservation(run_dir, name, duration, three_d and not preview):
        result = await _render_template(run_dir, template, params, duration, name, three_d, preview)
    if not three_d and not preview:
        _forget_3d(run_dir, name)
    return result


async def _render_template(
    run_dir: Path, template: str, params: dict, duration: float, name: str, three_d: bool, preview: bool
) -> dict[str, Any]:
    anim_dir = run_dir / "anim"
    work = anim_dir / ".work" / name
    work.mkdir(parents=True, exist_ok=True)
    # Les modèles s'appuient sur la charte `anim/lib/` (studio.js, studio3d.js, polices, icônes, carte) ; un run dir
    # créé avant l'arrivée du kit 3D (reprise) n'a pas encore ses fichiers.
    if not all((anim_dir / "lib" / f).exists() for f in ("studio.js", "studio3d.js", "three.bundle.min.js")):
        shutil.copytree(WORKSPACE_LIB, anim_dir / "lib", dirs_exist_ok=True)
    payload = json.dumps({**params, "duration": duration}, ensure_ascii=False).replace("</", "<\\/")
    html = (TEMPLATES_DIR / f"{template}.html").read_text(encoding="utf-8")
    page = anim_dir / f".tpl_{name}.html"
    page.write_text(html.replace("/*PARAMS*/{}", payload), encoding="utf-8")
    times, timeout_s = _render_plan(duration, three_d, preview)
    try:
        job = await run_sandboxed("html", page, anim_dir, work / "out", width=SHORT_WIDTH, height=SHORT_HEIGHT,
                                  fps=SHORT_FPS, duration=duration, trusted=True, webgl=three_d, times=times,
                                  timeout_s=timeout_s)
    except SandboxError as exc:
        raise ContractError(f"rendu du modèle {template} : {exc}") from exc
    finally:
        page.unlink(missing_ok=True)
    if preview:
        return await _preview(run_dir, name, work / "out", times or [], three_d, duration, job.get("warnings"))
    return await _finish(run_dir, name, work / "out", SHORT_FPS, duration, {"template": template},
                         job.get("warnings"))


async def animate_script(
    run_dir: Path, script_rel: str, duration: float, name: str, *, three_d: bool = False, preview: bool = False
) -> dict[str, Any]:
    _require("scripts")
    if three_d:
        _require_3d()
    if not scripts_supported():
        raise ContractError("scripts d'animation indisponibles : aucun bac à sable (bwrap / studio-sandbox)")
    anim_dir = (run_dir / "anim").resolve()
    script = resolve_in_run_dir(run_dir, script_rel, within="anim")
    if not script.is_file():
        raise ContractError(f"le script doit être un fichier existant de anim/ : {script_rel}")
    kind = SCRIPT_KINDS.get(script.suffix.lower())
    if kind is None:
        raise ContractError("extension acceptée : .html ou .py")
    if (three_d or preview) and kind != "html":
        raise ContractError("--3d / --preview : scripts HTML seulement (--3d avec lib/studio3d.js)")
    name, duration = _check_name(name), _check_duration(duration)
    if three_d:
        _check_3d_duration(duration)
    work = run_dir / "anim" / ".work" / name
    times, timeout_s = _render_plan(duration, three_d, preview)
    with _motion3d_reservation(run_dir, name, duration, three_d and not preview):
        try:
            job = await run_sandboxed(kind, script, anim_dir, work, width=SHORT_WIDTH, height=SHORT_HEIGHT,
                                      fps=SHORT_FPS, duration=duration, webgl=three_d, times=times,
                                      timeout_s=timeout_s)
        except SandboxError as exc:
            raise ContractError(f"{script_rel} : {exc}") from exc
        if preview:
            return await _preview(run_dir, name, work, times or [], three_d, duration, job.get("warnings"))
        result = await _finish(run_dir, name, work, SHORT_FPS, duration, {"script": script_rel}, job.get("warnings"))
    if not three_d:
        _forget_3d(run_dir, name)
    return result
