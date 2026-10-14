"""Boîte à outils CLI des rôles Claude Studio.

Usage (depuis le run dir, ou avec STUDIO_RUN_DIR) :
    python -m studio.tools <commande> [options]

Chaque commande écrit un JSON sur stdout ; en cas d'erreur, `{"error": ...}`
et code de sortie 1. Tous les chemins sont relatifs au run dir.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Le run dir est fixé avant tout import de `agent.*` : ce code suppose que le
# répertoire courant est la racine du repo (`.env`, `data/agent_config.json`).
RUN_DIR = Path(os.getenv("STUDIO_RUN_DIR") or os.getcwd()).resolve()
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)

from agent.core.config import load_agent_config  # noqa: E402
from studio import media  # noqa: E402
from studio.contracts import ContractError, read_json, resolve_in_run_dir, write_json  # noqa: E402


def _read_brief(run_dir: Path) -> dict[str, Any]:
    try:
        data = read_json(run_dir / "brief.json", {})
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _engine_key(engine: object) -> str:
    """Nom de moteur TTS de la chaîne de repli (`edge-tts` → `edge`)."""
    name = str(engine or "").strip().lower()
    return "edge" if name == "edge-tts" else name


# ── commandes ─────────────────────────────────────────────────────────────


async def cmd_search_media(args: argparse.Namespace, run_dir: Path) -> Any:
    sources = [s.strip() for s in args.sources.split(",")] if args.sources else None
    results = await media.search_media(
        run_dir, args.query, media_type=args.type, sources=sources, orientation=args.orientation
    )
    return {"query": args.query, "count": len(results), "results": results}


async def cmd_preview(args: argparse.Namespace, run_dir: Path) -> Any:
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    if not ids:
        raise ValueError("--ids vide")
    if len(ids) > 12:
        raise ValueError("12 candidats maximum par planche")
    return await media.preview_candidates(run_dir, ids)


async def cmd_download(args: argparse.Namespace, run_dir: Path) -> Any:
    return await media.download_candidate(run_dir, args.id, args.name)


async def cmd_ai_image(args: argparse.Namespace, run_dir: Path) -> Any:
    return await media.generate_ai_image(run_dir, args.prompt, args.name, args.aspect)


async def cmd_music(args: argparse.Namespace, run_dir: Path) -> Any:
    return await media.fetch_music(run_dir, args.mood)


def _tts_engine_chain(run_dir: Path, requested: str | None) -> tuple[list[str], dict[str, str]]:
    """Moteurs à essayer dans l'ordre et voix de chacun.

    Moteur/voix de la chaîne (résolus avec les plafonds d'abonnement dans `brief.json`),
    sinon défauts globaux ; repli : moteur demandé → Gemini → edge-tts (gratuit, sans clé).
    """
    tts_cfg = load_agent_config().get("tts", {})
    short_cfg = tts_cfg.get("short", {})
    brief = _read_brief(run_dir)
    brief_engine = _engine_key(brief.get("tts_engine"))
    primary = _engine_key(requested) or brief_engine or _engine_key(short_cfg.get("engine")) or "azure"
    chain = [primary] + [e for e in ("gemini", "edge") if e != primary]
    voices = {
        "azure": short_cfg.get("voice", "fr-FR-Vivienne:DragonHDLatestNeural"),
        "gemini": tts_cfg.get("gemini", {}).get("voice", "Leda"),
        "edge": tts_cfg.get("fallback_voice", "fr-FR-RemyMultilingualNeural"),
    }
    if brief_engine and brief.get("voice"):
        voices[brief_engine] = str(brief["voice"])
    return chain, voices


async def _synthesize(
    segments: list[tuple[str, dict]], out: Path, *, engine: str, voice: str, args: argparse.Namespace
) -> tuple[float, str]:
    """Synthétise chaque ligne (emphase propre) puis les recolle ; renvoie (durée, moteur effectif)."""
    from agent.skills.audio.tts import generate_tts
    from studio.voicefx import combine_offset, concat_wavs

    if not segments:
        raise ValueError("texte vide : rien à synthétiser")
    parts: list[Path] = []
    try:
        for i, (seg_text, opts) in enumerate(segments):
            part = out if len(segments) == 1 else out.with_name(f".{out.stem}_part{i:02d}.wav")
            duration, used = await generate_tts(
                seg_text,
                part,
                voice=voice,
                engine=engine,
                tts_style=args.style or "narration-professional",
                tts_rate=combine_offset(args.rate, opts.get("rate")),
                tts_pitch=combine_offset(args.pitch, opts.get("pitch")),
                mood=args.mood or "",
            )
            parts.append(part)
        return (duration if len(parts) == 1 else concat_wavs(parts, out)), used
    finally:
        for p in out.parent.glob(f".{out.stem}_part*.wav"):
            p.unlink(missing_ok=True)


async def cmd_tts(args: argparse.Namespace, run_dir: Path) -> Any:
    from studio.voicefx import has_emphasis, parse_emphasis, tighten_pauses

    text = resolve_in_run_dir(run_dir, args.text_file).read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{args.text_file} est vide")
    out = resolve_in_run_dir(run_dir, args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    chain, voices = _tts_engine_chain(run_dir, args.engine)
    # Emphase par ligne (`[rate=+12% pitch=+4Hz] Nous !`) : chaque ligne est synthétisée avec ses réglages
    # puis recollée (edge-tts n'accepte pas de SSML).
    segments = parse_emphasis(text) if has_emphasis(text) else [(text, {})]
    errors: dict[str, str] = {}
    for engine in chain:
        voice = args.voice if (args.voice and engine == chain[0]) else voices.get(engine, "")
        try:
            duration, used = await _synthesize(segments, out, engine=engine, voice=voice, args=args)
        except Exception as exc:
            errors[engine] = str(exc)[:200]
            continue
        tightened = tighten_pauses(out, max_pause_s=args.max_pause) if args.max_pause > 0 else None
        if tightened:
            duration = tightened["after_s"]
        return {
            "path": args.out,
            "duration_s": round(duration, 3),
            **({"pauses_removed_s": tightened["removed_s"]} if tightened else {}),
            "engine": used,
            "voice": voice,
            "chars": len(text),
            **({"fallback_errors": errors} if errors else {}),
        }
    raise RuntimeError(f"tous les moteurs TTS ont échoué : {errors}")


async def cmd_transcribe(args: argparse.Namespace, run_dir: Path) -> Any:
    from agent.skills.audio.whisper_utils import transcribe_to_words

    # `small` par défaut : le texte est connu, Whisper ne sert qu'au calage mot à mot,
    # et large-v3 (~3 Go de RAM) fait swapper les petites machines.
    model = args.model or os.getenv("STUDIO_WHISPER_MODEL", "small")
    audio = resolve_in_run_dir(run_dir, args.audio)
    if not audio.exists():
        raise FileNotFoundError(f"{args.audio} introuvable")
    words = await transcribe_to_words([audio], model_name=model, language=args.language)
    payload = [{"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3)} for w in words]
    transcript = " ".join(w["word"] for w in payload)
    if args.text_file:
        from studio.align import align_words

        script = resolve_in_run_dir(run_dir, args.text_file).read_text(encoding="utf-8")
        payload = align_words(payload, script)
    out = resolve_in_run_dir(run_dir, args.out)
    write_json(out, payload, indent=1)
    return {
        "path": args.out,
        "words": len(payload),
        "end_s": payload[-1]["end"] if payload else 0.0,
        # Ce que Whisper a entendu (pour vérifier la prononciation), avant recalage.
        "transcript": transcript,
    }


async def cmd_cues(args: argparse.Namespace, run_dir: Path) -> Any:
    """Mots d'un plan avec leur instant relatif au début du plan (valeurs `at` du kit d'animation)."""
    words = read_json(resolve_in_run_dir(run_dir, args.words), [])
    start, end = args.start, args.end if args.end is not None else float("inf")
    cues = [
        {"word": w["word"], "at": round(w["start"] - start, 2), "end": round(w["end"] - start, 2)}
        for w in words
        if start - 0.05 <= w["start"] < end
    ]
    return {"start": start, "end": None if end == float("inf") else end, "cues": cues}


async def cmd_render(args: argparse.Namespace, run_dir: Path) -> Any:
    from studio.render import render_timeline

    return await render_timeline(run_dir, resolve_in_run_dir(run_dir, args.timeline), Path(args.out))


async def cmd_frames(args: argparse.Namespace, run_dir: Path) -> Any:
    video = resolve_in_run_dir(run_dir, args.video)
    out_dir = resolve_in_run_dir(run_dir, args.out or f"review/{video.stem}")
    return await media.extract_frames(run_dir, video, args.every, out_dir)


async def cmd_analyze(args: argparse.Namespace, run_dir: Path) -> Any:
    from studio.analyze import analyze_video

    video = resolve_in_run_dir(run_dir, args.video)
    if not video.exists():
        raise FileNotFoundError(f"{args.video} introuvable")
    out_dir = resolve_in_run_dir(run_dir, args.out or f"review/{video.stem}/analysis")
    words = resolve_in_run_dir(run_dir, args.words) if args.words else None
    timeline = resolve_in_run_dir(run_dir, args.timeline) if args.timeline else None
    return await analyze_video(
        run_dir, video, out_dir, engine=args.engine, words_file=words, timeline_file=timeline,
        every_s=args.every, context=args.context or "",
    )


async def cmd_thumbnail(args: argparse.Namespace, run_dir: Path) -> Any:
    from studio.thumbnail import compose_thumbnail

    return await compose_thumbnail(
        run_dir,
        args.background,
        args.text,
        resolve_in_run_dir(run_dir, args.out),
        aspect=args.aspect,
        position=args.position,
        color=args.color,
    )


async def cmd_animate_template(args: argparse.Namespace, run_dir: Path) -> Any:
    from studio.animate import animate_template

    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as exc:
        raise ContractError(f"--params doit être un objet JSON : {exc}") from exc
    if not isinstance(params, dict):
        raise ContractError("--params doit être un objet JSON")
    return await animate_template(run_dir, args.template, params, args.duration, args.name)


async def cmd_animate(args: argparse.Namespace, run_dir: Path) -> Any:
    from studio.animate import animate_script

    return await animate_script(run_dir, args.script, args.duration, args.name)


async def cmd_probe(args: argparse.Namespace, run_dir: Path) -> Any:
    path = resolve_in_run_dir(run_dir, args.path)
    info = await media.probe_media(path)
    if info["has_audio"] and args.loudness:
        info["loudness_lufs"] = await media.loudness(path)
    return {"path": args.path, **info}


async def cmd_validate(args: argparse.Namespace, run_dir: Path) -> Any:
    from studio import contracts

    models = {
        "brief": contracts.Brief,
        "scenario": contracts.Scenario,
        "timeline": contracts.Timeline,
        "critique": contracts.Critique,
        "thumbnail": contracts.Thumbnail,
        "result": contracts.StudioResult,
    }
    model = models[args.kind]
    contracts.load_contract(resolve_in_run_dir(run_dir, args.path), model)
    return {"path": args.path, "valid": True}


# ── parser ────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m studio.tools", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search-media", help="cherche images/vidéos libres dans les banques")
    p.add_argument("--query", required=True, help="mots-clés (anglais conseillé pour les banques)")
    p.add_argument("--type", choices=["image", "video"], default="image")
    p.add_argument("--sources", help=f"liste séparée par des virgules parmi : {','.join(media.SOURCES)}")
    p.add_argument("--orientation", choices=["portrait", "landscape"], default="portrait")
    p.set_defaults(func=cmd_search_media)

    p = sub.add_parser("preview", help="planche contact de candidats (à lire avec Read)")
    p.add_argument("--ids", required=True, help="ids séparés par des virgules (max 12)")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("download", help="télécharge un candidat dans media/<name>.<ext>")
    p.add_argument("--id", required=True)
    p.add_argument("--name", required=True, help="nom de fichier sans extension, ex. 03_volcan")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("ai-image", help="génère une image IA (Flux) en dernier recours")
    p.add_argument("--prompt", required=True, help="prompt en anglais, sans texte dans l'image")
    p.add_argument("--name", required=True)
    p.add_argument("--aspect", choices=["9:16", "16:9"], default="9:16")
    p.set_defaults(func=cmd_ai_image)

    p = sub.add_parser("music", help="télécharge une musique de fond libre")
    p.add_argument(
        "--mood", required=True,
        help="energique|calme|dramatique|mysterieux|inspirant|humoristique|tension|revelateur",
    )
    p.set_defaults(func=cmd_music)

    p = sub.add_parser("tts", help="synthèse vocale d'un fichier texte")
    p.add_argument("--text-file", required=True)
    p.add_argument("--out", default="voice.wav")
    p.add_argument("--voice", help="voix (défaut : tts.short de data/agent_config.json)")
    p.add_argument("--engine", choices=["azure", "gemini", "edge"])
    p.add_argument("--style", help="style Azure (narration-professional, cheerful, excited…)")
    p.add_argument("--rate", default="+0%", help="débit, ex. +8%%")
    p.add_argument("--pitch", default="+0Hz", help="hauteur, ex. -2Hz (edge, Azure)")
    p.add_argument(
        "--max-pause", type=float, default=0.4,
        help="raccourcit les silences plus longs (s) ; 0 = laisser tel quel",
    )
    p.add_argument("--mood", help="ambiance (dramatique, mysterieux, energique…)")
    p.set_defaults(func=cmd_tts)

    p = sub.add_parser("transcribe", help="timestamps mot à mot (Whisper)")
    p.add_argument("--audio", default="voice.wav")
    p.add_argument("--out", default="words.json")
    p.add_argument("--language", default="fr")
    p.add_argument("--model", help="modèle Whisper (défaut STUDIO_WHISPER_MODEL ou small)")
    p.add_argument("--text-file", help="script exact : les sous-titres en reprennent l'orthographe")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("cues", help="mots d'un plan avec leur instant relatif (pour caler les animations)")
    p.add_argument("--start", type=float, required=True, help="début du plan dans la voix (s)")
    p.add_argument("--end", type=float, help="fin du plan (s)")
    p.add_argument("--words", default="words.json")
    p.set_defaults(func=cmd_cues)

    p = sub.add_parser("render", help="rend timeline.json en Short 9:16")
    p.add_argument("--timeline", default="timeline.json")
    p.add_argument("--out", required=True, help="ex. renders/v1.mp4")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("frames", help="frames + planche contact d'une vidéo")
    p.add_argument("--video", required=True)
    p.add_argument("--every", type=float, default=2.0, help="intervalle en secondes")
    p.add_argument("--out", help="dossier (défaut review/<nom>)")
    p.set_defaults(func=cmd_frames)

    p = sub.add_parser("analyze", help="analyse multimodale d'une vidéo (Gemini, sinon matériaux pour Claude)")
    p.add_argument("--video", required=True)
    p.add_argument("--out", help="dossier (défaut review/<nom>/analysis)")
    p.add_argument("--engine", choices=["auto", "gemini", "claude"], default="auto")
    p.add_argument("--words", help="words.json existant (évite une transcription Whisper)")
    p.add_argument("--timeline", help="timeline.json du rendu : coupes exactes (sinon détectées à l'image)")
    p.add_argument("--every", type=float, default=1.0, help="pas de la planche chronologique (s)")
    p.add_argument("--context", help="contexte pour Gemini (sujet, cible)")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("thumbnail", help="compose une miniature avec texte")
    p.add_argument("--background", required=True, help="media/x.jpg ou renders/v1.mp4@3.5")
    p.add_argument("--text", required=True, help="texte court ; « | » pour aller à la ligne")
    p.add_argument("--out", required=True)
    p.add_argument("--aspect", choices=["9:16", "16:9"], default="9:16")
    p.add_argument("--position", choices=["top", "center", "bottom"], default="center")
    p.add_argument("--color", default="yellow", help="couleur ffmpeg (yellow, white, #FF3B30…)")
    p.set_defaults(func=cmd_thumbnail)

    p = sub.add_parser("animate-template", help="animation prête (title, counter, bars, list) → media/anim_<name>.mp4")
    p.add_argument("--template", required=True)
    p.add_argument("--params", default="{}", help="objet JSON des paramètres du modèle")
    p.add_argument("--duration", type=float, required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_animate_template)

    p = sub.add_parser("animate", help="rend un script jetable anim/<x>.html|.py (bac à sable) → media/anim_<name>.mp4")
    p.add_argument("--script", required=True)
    p.add_argument("--duration", type=float, required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_animate)

    p = sub.add_parser("probe", help="durée, résolution, audio d'un fichier")
    p.add_argument("--path", required=True)
    p.add_argument("--loudness", action="store_true")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("validate", help="valide un fichier de contrat")
    p.add_argument("--kind", required=True, choices=["brief", "scenario", "timeline", "critique", "thumbnail", "result"])
    p.add_argument("--path", required=True)
    p.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.getenv("STUDIO_LOG_LEVEL", "ERROR"), stream=sys.stderr)
    args = build_parser().parse_args(argv)
    run_dir = RUN_DIR
    try:
        result = asyncio.run(args.func(args, run_dir))
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
