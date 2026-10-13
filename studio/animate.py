"""Animations des Shorts : modèles intégrés et scripts jetables écrits par Claude.

Le niveau autorisé vient de `STUDIO_ANIMATIONS` (posé par le launcher depuis le
brief, hors de portée de Claude) : `off` | `templates` | `scripts`. Les images
sont produites dans le bac à sable (`studio/sandbox.py`) puis encodées ici en un
clip 1080×1920 sans audio, utilisable tel quel comme `clip.media` d'une timeline.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Literal

from agent.skills.video.ffmpeg_runtime import filter_thread_args, run_ffmpeg, thread_args
from agent.skills.video.ken_burns import SHORT_FPS, SHORT_HEIGHT, SHORT_WIDTH
from studio.contracts import ContractError
from studio.media import extract_frames, record_credit
from studio.sandbox import SandboxError, run_sandboxed, scripts_supported

AnimationPolicy = Literal["off", "templates", "scripts"]
ANIMATION_POLICIES: tuple[AnimationPolicy, ...] = ("off", "templates", "scripts")
TEMPLATES_DIR = Path(__file__).resolve().parent / "anim_templates"
TEMPLATES = ("title", "counter", "bars", "list", "compare", "steps", "map", "before_after", "paradox")
WORKSPACE_LIB = Path(__file__).resolve().parent / "workspace" / "anim" / "lib"
MAX_DURATION_S = 12.0
SCRIPT_KINDS = {".html": "html", ".htm": "html", ".py": "python"}


def animation_policy() -> AnimationPolicy:
    value = os.getenv("STUDIO_ANIMATIONS", "scripts").strip().lower()
    return value if value in ANIMATION_POLICIES else "off"  # type: ignore[return-value]


def _require(level: AnimationPolicy) -> None:
    policy = animation_policy()
    if ANIMATION_POLICIES.index(policy) < ANIMATION_POLICIES.index(level):
        allowed = {"off": "aucune animation", "templates": "uniquement animate-template"}[policy]
        raise ContractError(f"animations non autorisées pour cette chaîne ({policy} : {allowed})")


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
    await _encode(work / "frames", fps, duration, out)
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
        result["hint"] = "corrige ces positions (contenu entre y 170 et 1180, x 60 et 960) puis relance"
    return result


async def animate_template(run_dir: Path, template: str, params: dict, duration: float, name: str) -> dict[str, Any]:
    _require("templates")
    if template not in TEMPLATES:
        raise ContractError(f"modèle inconnu : {template} (disponibles : {', '.join(TEMPLATES)})")
    name, duration = _check_name(name), _check_duration(duration)
    anim_dir = run_dir / "anim"
    work = anim_dir / ".work" / name
    work.mkdir(parents=True, exist_ok=True)
    # Les modèles s'appuient sur la charte `anim/lib/` (studio.js, polices, icônes, carte).
    if not (anim_dir / "lib" / "studio.js").exists():
        shutil.copytree(WORKSPACE_LIB, anim_dir / "lib", dirs_exist_ok=True)
    payload = json.dumps({**params, "duration": duration}, ensure_ascii=False).replace("</", "<\\/")
    html = (TEMPLATES_DIR / f"{template}.html").read_text(encoding="utf-8")
    page = anim_dir / f".tpl_{name}.html"
    page.write_text(html.replace("/*PARAMS*/{}", payload), encoding="utf-8")
    try:
        job = await run_sandboxed("html", page, anim_dir, work / "out", width=SHORT_WIDTH, height=SHORT_HEIGHT,
                                  fps=SHORT_FPS, duration=duration, trusted=True)
    except SandboxError as exc:
        raise ContractError(f"rendu du modèle {template} : {exc}") from exc
    finally:
        page.unlink(missing_ok=True)
    return await _finish(run_dir, name, work / "out", SHORT_FPS, duration, {"template": template},
                         job.get("warnings"))


async def animate_script(run_dir: Path, script_rel: str, duration: float, name: str) -> dict[str, Any]:
    _require("scripts")
    if not scripts_supported():
        raise ContractError("scripts d'animation indisponibles : aucun bac à sable (bwrap / studio-sandbox)")
    anim_dir = (run_dir / "anim").resolve()
    script = (run_dir / script_rel).resolve()
    if not script.is_relative_to(anim_dir) or not script.is_file():
        raise ContractError(f"le script doit être un fichier existant de anim/ : {script_rel}")
    kind = SCRIPT_KINDS.get(script.suffix.lower())
    if kind is None:
        raise ContractError("extension acceptée : .html ou .py")
    name, duration = _check_name(name), _check_duration(duration)
    work = run_dir / "anim" / ".work" / name
    try:
        job = await run_sandboxed(kind, script, anim_dir, work, width=SHORT_WIDTH, height=SHORT_HEIGHT,
                                  fps=SHORT_FPS, duration=duration)
    except SandboxError as exc:
        raise ContractError(f"{script_rel} : {exc}") from exc
    return await _finish(run_dir, name, work, SHORT_FPS, duration, {"script": script_rel}, job.get("warnings"))
