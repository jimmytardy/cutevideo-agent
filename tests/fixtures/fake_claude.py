"""Faux `claude` CLI pour tester la génération complète d'un Short sans appeler Claude.

Il joue le rôle du producteur de `/make-video` de façon déterministe, dans le
run dir préparé par `studio.launcher` : il vérifie le contrat d'appel (options,
workspace copié, environnement), produit chaque fichier du pipeline en appelant
les VRAIS outils (`python -m studio.tools …` : validate, render, frames,
thumbnail, probe) et émet le même stream-json que Claude Code, sous-agents
(`Task`) compris. Boucle scénario en deux passes (l'analyse 1 demande une
vérification de fait au scénariste, l'analyse 2 approuve), puis deux itérations
vidéo : la critique 1 demande une reprise au monteur, la critique 2 approuve.

Reprise après interruption : `--session-id` enregistre une fausse transcription
dans `CLAUDE_CONFIG_DIR/projects/`, `--resume` la réclame (« No conversation
found » sinon, comme le vrai CLI) ; les étapes dont les fichiers existent déjà
sont sautées. `FAKE_CLAUDE_HANG_IN=<rôle>` lance ce sous-agent puis bloque (le
test interrompt alors le worker en pleine étape) ; jamais lors d'une reprise.
`FAKE_CLAUDE_LIMIT_IN=<rôle>` simule la limite d'usage de l'abonnement pendant ce
rôle (`rate_limit_event` refusé, reset dans 3 s, session en erreur), une seule fois
par run dir.

Seuls le contenu « créatif » (script, critique) et les médias sources sont
synthétiques : la voix est un signal ffmpeg et les médias des mires, pour que le
test tourne hors ligne.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

RUN_DIR = Path.cwd()
ROLES = ("scenariste", "critique-scenario", "voix", "monteur", "miniaturiste", "critique")
VOICE_S = 3.0
BEATS = ["Un flamant rose naît gris.", "Il mange sa couleur.", "Et toi, tu es de quelle couleur ?"]
_counter = 0


# Script jetable « écrit par Claude » : rendu image par image via renderFrame(t).
ANIM_SCRIPT = """<!doctype html><html><body style="margin:0;width:1080px;height:1920px;background:#102">
<canvas id="c" width="1080" height="1920"></canvas><script>
const ctx = document.getElementById("c").getContext("2d");
window.renderFrame = (t) => {
  ctx.fillStyle = "#102"; ctx.fillRect(0, 0, 1080, 1920);
  ctx.fillStyle = "#ff6fae"; ctx.beginPath(); ctx.arc(540, 700, 80 + 300 * Math.min(t, 1), 0, 2 * Math.PI); ctx.fill();
};
</script></body></html>
"""


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _next_id(prefix: str) -> str:
    global _counter
    _counter += 1
    return f"{prefix}_{_counter:03d}"


def fail(message: str) -> None:
    emit({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": message})
    sys.exit(1)


RESUME_PROMPT_START = "La session a été interrompue"


def check_invocation(argv: list[str]) -> None:
    """Le lanceur doit appeler le CLI comme le ferait la production."""
    resuming = "--resume" in argv
    if argv[0] != "-p" or not (argv[1] == "/make-video" or (resuming and argv[1].startswith(RESUME_PROMPT_START))):
        fail(f"prompt inattendu : {argv[:2]}")
    session_flags = [flag for flag in ("--session-id", "--resume", "--no-session-persistence") if flag in argv]
    if len(session_flags) != 1:
        fail(f"une seule option de session attendue : {session_flags}")
    for flag in ("--output-format", "--verbose", "--allowedTools", "--permission-mode", "--model"):
        if flag not in argv:
            fail(f"option manquante : {flag}")
    if argv[argv.index("--output-format") + 1] != "stream-json":
        fail("stream-json attendu")
    if argv[argv.index("--permission-mode") + 1] != "dontAsk":
        fail("permission-mode dontAsk attendu")
    if "Bash(python -m studio.tools:*)" not in argv:
        fail("Bash doit être restreint à studio.tools")
    for rel in ["CLAUDE.md", "brief.json", ".claude/commands/make-video.md",
                *[f".claude/agents/{r}.md" for r in ROLES]]:
        if not (RUN_DIR / rel).is_file():
            fail(f"workspace incomplet : {rel}")
    if Path(os.environ.get("STUDIO_RUN_DIR", "")).resolve() != RUN_DIR.resolve():
        fail("STUDIO_RUN_DIR doit pointer sur le run dir")
    brief = json.loads((RUN_DIR / "brief.json").read_text(encoding="utf-8"))
    if os.environ.get("STUDIO_ANIMATIONS") != brief.get("animations", "scripts"):
        fail("STUDIO_ANIMATIONS doit refléter brief.animations (posé par le launcher)")
    if not (RUN_DIR / "anim" / "lib" / "gsap.min.js").is_file():
        fail("libs d'animation absentes du run dir (anim/lib)")
    leaked = [name for name in ("GOOGLE_GEMINI_API_KEY", "FAL_KEY", "AZURE_SPEECH_KEY")
              if os.environ.get(name)]
    if leaked:
        fail(f"clés de plateforme transmises au CLI (seules celles de l'utilisateur doivent l'être) : {leaked}")


def tool(parent: str, *args: str) -> dict:
    """Appel d'un outil studio comme le ferait un sous-agent (Bash)."""
    command = ["python", "-m", "studio.tools", *args]
    tid = _next_id("bash")
    emit({"type": "assistant", "parent_tool_use_id": parent, "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": " ".join(command)}}]}})
    proc = subprocess.run(command, capture_output=True, text=True, cwd=RUN_DIR)
    emit({"type": "user", "parent_tool_use_id": parent, "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": proc.stdout, "is_error": proc.returncode != 0}]}})
    if proc.returncode != 0:
        fail(f"studio.tools {' '.join(args)} a échoué : {proc.stdout} {proc.stderr[-500:]}")
    return json.loads(proc.stdout)


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def write_json(rel: str, data: object) -> None:
    path = RUN_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Subagent:
    def __init__(self, role: str, iteration: int) -> None:
        self.role = role
        self.id = _next_id(f"task_{role}")
        emit({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [{
            "type": "tool_use", "id": self.id, "name": "Task",
            "input": {"subagent_type": role, "description": f"{role} itération {iteration}",
                      "prompt": f"Itération {iteration}"}}]}})

    def done(self, report: str) -> None:
        emit({"type": "user", "parent_tool_use_id": None, "message": {"content": [{
            "type": "tool_result", "tool_use_id": self.id,
            "content": [{"type": "text", "text": f"Rapport.\nThe report follows:\n  {report}\nagentId: x"}]}]}})


def scenariste(brief: dict, attempt: int = 1) -> None:
    agent = Subagent("scenariste", 1)
    # Passe 2 : le fait signalé par l'analyse scénario a été vérifié en ligne.
    sources = [{"claim": "les flamants naissent gris", "url": "https://fr.wikipedia.org/wiki/Flamant_rose"}]
    write_json("scenario.json", {
        "title": brief["theme"],
        "hook": BEATS[0],
        "beats": [
            {"text": BEATS[0], "visual_intent": "poussin gris", "on_screen_text": "NÉ GRIS"},
            {"text": BEATS[1], "visual_intent": "flamant qui mange"},
            {"text": BEATS[2], "visual_intent": "silhouette"},
        ],
        "cta": "",
        "mood": "calme",
        "music_mood": "",
        "visual_mode": _visual_mode(),
        "publish": {"title": "Les flamants naissent gris", "description": "Leur couleur vient de leur assiette.",
                    "hashtags": ["#shorts", "#animaux"], "tiktok_caption": "Un flamant rose… gris ?",
                    "instagram_caption": "Leur couleur vient de leur assiette. Vous le saviez ?"},
        "sources": sources if attempt >= 2 else [],
    })
    tool(agent.id, "validate", "--kind", "scenario", "--path", "scenario.json")
    (RUN_DIR / f"scenario_v{attempt}.json").write_text((RUN_DIR / "scenario.json").read_text(encoding="utf-8"),
                                                       encoding="utf-8")
    agent.done("3 beats, 15 mots.")


def critique_scenario(attempt: int) -> None:
    agent = Subagent("critique-scenario", 1)
    approve = attempt >= 2
    write_json(f"scenario_critique_{attempt}.json", {
        "iteration": attempt, "score": 93 if approve else 82, "decision": "approve" if approve else "iterate",
        "summary": "ok" if approve else "Fait non sourcé.",
        "unverified_claims": [] if approve else ["« naît gris » : à vérifier sur le web"],
        "changes": [] if approve else ["beat 1 : garder le hook, sourcer le fait"],
        "scores": {"hook": 18, "structure": 13, "valeur_verite": 19 if approve else 10},
    })
    tool(agent.id, "validate", "--kind", "scenario-critique", "--path", f"scenario_critique_{attempt}.json")
    agent.done(f"Score {93 if approve else 82}.")


def voix() -> None:
    agent = Subagent("voix", 1)
    (RUN_DIR / "subtitles.txt").write_text("\n".join(BEATS), encoding="utf-8")
    (RUN_DIR / "narration.txt").write_text("\n".join(BEATS), encoding="utf-8")
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency=220:duration={VOICE_S}", "-ar", "48000", str(RUN_DIR / "voice.wav"))
    words = " ".join(BEATS).split()
    step = VOICE_S / len(words)
    write_json("words.json", [
        {"word": w, "start": round(i * step, 3), "end": round((i + 1) * step - 0.02, 3)} for i, w in enumerate(words)
    ])
    probe = tool(agent.id, "probe", "--path", "voice.wav")
    write_json("voice.json", {"duration_s": probe["duration_s"], "engine": "test", "voice": "sine"})
    agent.done(f"Durée {probe['duration_s']} s.")


def monteur(iteration: int) -> None:
    agent = Subagent("monteur", iteration)
    media = RUN_DIR / "media"
    media.mkdir(exist_ok=True)
    if iteration == 1:
        ffmpeg("-f", "lavfi", "-i", "testsrc=size=720x1280", "-frames:v", "1", str(media / "01_poussin.png"))
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "0.8", "-pix_fmt", "yuv420p",
               str(media / "02_repas.mp4"))
        ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=640x640", "-frames:v", "1", str(media / "03_silhouette.png"))
        write_json("media/credits.json", {
            f"media/{name}": {"source": "pexels", "license": "pexels", "author": "Test",
                              "attribution": f"Photo par Test via Pexels ({name})", "source_url": None,
                              "requires_attribution": False}
            for name in ("01_poussin.png", "02_repas.mp4", "03_silhouette.png")
        })
    clips = [
        {"media": "media/01_poussin.png", "start": 0.0, "end": 1.0,
         "motion": "zoom" if iteration == 1 else "pan_left", "text": "NÉ GRIS"},
        {"media": "media/02_repas.mp4", "start": 1.0, "end": 2.0, "video_offset": 0.2},
        {"media": "media/03_silhouette.png", "start": 2.0, "end": VOICE_S, "motion": "pan_right"},
    ]
    # Itération 2 (correction demandée par la critique) : plans animés selon brief.animations.
    animations = json.loads((RUN_DIR / "brief.json").read_text(encoding="utf-8")).get("animations", "off")
    if iteration == 2 and animations == "scripts":
        (RUN_DIR / "anim" / "02_schema.html").write_text(ANIM_SCRIPT, encoding="utf-8")
        anim = tool(agent.id, "animate", "--script", "anim/02_schema.html", "--duration", "1", "--name", "02_schema")
        clips[1] = {"media": anim["media"], "start": 1.0, "end": 2.0, "motion": "static", "video_offset": 0}
    if iteration == 2 and animations in ("templates", "scripts"):
        anim = tool(agent.id, "animate-template", "--template", "compare", "--duration", "1.2", "--name", "03_chiffre",
                    "--params", json.dumps({"title": "GRIS → ROSE", "left": {"label": "Poussin", "value": "0 an",
                                            "icon": "bird"}, "right": {"label": "Adulte", "value": "3 ans"}}))
        clips[2] = {"media": anim["media"], "start": 2.0, "end": VOICE_S, "motion": "static", "video_offset": 0}
    if iteration == 2:
        clips[1]["sfx"] = "whoosh"
        clips[2]["sfx"] = "pop"
    write_json("timeline.json", {
        "voice": "voice.wav", "words": "words.json", "music": None, "subtitles": True, "clips": clips,
        "subtitle_keywords": ["flamant"],
    })
    tool(agent.id, "validate", "--kind", "timeline", "--path", "timeline.json")
    tool(agent.id, "render", "--out", f"renders/v{iteration}.mp4")
    tool(agent.id, "frames", "--video", f"renders/v{iteration}.mp4", "--every", "1")
    agent.done(f"3 plans, renders/v{iteration}.mp4.")


def miniaturiste(iteration: int) -> None:
    """Une seule fois, après la boucle, sur la vidéo finale."""
    agent = Subagent("miniaturiste", iteration)
    tool(agent.id, "frames", "--video", f"renders/v{iteration}.mp4", "--every", "5")
    for aspect, name in (("9:16", "final_9x16"), ("16:9", "final_16x9")):
        tool(agent.id, "thumbnail", "--background", "media/01_poussin.png", "--text", "NÉ|GRIS",
             "--aspect", aspect, "--out", f"thumbnails/{name}.png")
    write_json("thumbnail.json", {"vertical": "thumbnails/final_9x16.png", "horizontal": "thumbnails/final_16x9.png",
                                  "text": "NÉ|GRIS", "background": "media/01_poussin.png"})
    tool(agent.id, "validate", "--kind", "thumbnail", "--path", "thumbnail.json")
    agent.done("Texte « NÉ GRIS ».")


def critique(iteration: int) -> None:
    agent = Subagent("critique", iteration)
    analysis = tool(agent.id, "analyze", "--video", f"renders/v{iteration}.mp4", "--words", "words.json", "--timeline", "timeline.json",
                    "--engine", "claude")
    approve = iteration >= 2
    write_json(f"critique_{iteration}.json", {
        "iteration": iteration, "video": f"renders/v{iteration}.mp4",
        "score": 86 if approve else 70, "decision": "approve" if approve else "iterate",
        "summary": "ok" if approve else "Plan 1 trop statique.",
        "strengths": ["rythme"], "issues": [] if approve else ["plan 1 statique"],
        "changes": [] if approve else [{"role": "monteur", "instruction": "plan 1 : panoramique"}],
        "scores": {"hook": 16 if approve else 12, "retention": 12, "valeur": 12},
        "analysis": {"source": analysis["source"], "path": analysis["analysis"], "flags": analysis["flags"][:3]},
    })
    tool(agent.id, "validate", "--kind", "critique", "--path", f"critique_{iteration}.json")
    agent.done(f"Score {86 if approve else 70}.")


def _session_file(session_id: str) -> Path:
    project_dir = "-" + str(RUN_DIR.resolve()).strip("/").replace("/", "-")
    return Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / project_dir / f"{session_id}.jsonl"


def open_session(argv: list[str]) -> None:
    """Fausse transcription : créée par --session-id, exigée par --resume."""
    if "--session-id" in argv:
        path = _session_file(argv[argv.index("--session-id") + 1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    elif "--resume" in argv:
        session_id = argv[argv.index("--resume") + 1]
        if not _session_file(session_id).is_file():
            emit({"type": "result", "subtype": "error_during_execution", "is_error": True, "num_turns": 0,
                  "errors": [f"No conversation found with session ID: {session_id}"]})
            sys.exit(1)


def _visual_mode() -> str:
    """Le mode qu'exige le style visuel de la chaîne (posé par le launcher), comme le ferait le scénariste."""
    if os.environ.get("STUDIO_ANIMATIONS") == "off":
        return "footage"
    return {"mixed": "mixed", "realistic": "footage"}.get(os.environ.get("STUDIO_VISUAL_STYLE", ""), "animation")


def hit_usage_limit(role: str) -> None:
    """Limite de l'abonnement pendant `role`, sous la forme réelle de `claude -p` (anthropics/claude-code#57096) :
    sous-agent arrêté, `rate_limit_event` refusé, message assistant synthétique, `result` en erreur sans texte."""
    (RUN_DIR / ".fake_limit_hit").write_text(role, encoding="utf-8")
    agent = Subagent(role.split("_")[0], 1)
    reset = int(time.time()) + 3
    message = "You've hit your session limit · resets 3:45pm"
    emit({"type": "rate_limit_event", "rate_limit_info": {
        "status": "rejected", "resetsAt": reset, "rateLimitType": "five_hour", "overageStatus": "rejected",
        "overageDisabledReason": "org_level_disabled", "isUsingOverage": False}})
    emit({"type": "user", "parent_tool_use_id": None, "message": {"content": [{
        "type": "tool_result", "tool_use_id": agent.id, "is_error": True,
        "content": [{"type": "text", "text": f"Agent terminated early due to an API error: {message}"}]}]}})
    emit({"type": "assistant", "message": {"model": "<synthetic>", "content": [{"type": "text", "text": message}]},
          "error": "rate_limit", "isApiErrorMessage": True, "apiErrorStatus": 429})
    emit({"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429, "num_turns": 7,
          "result": ""})
    sys.exit(1)


def step(role: str, done: bool, run) -> None:
    """Exécute un rôle sauf si ses fichiers existent déjà (reprise) ; bloque ou atteint la limite si demandé."""
    if done:
        return
    if os.environ.get("FAKE_CLAUDE_HANG_IN") == role and not (RUN_DIR / "resume.json").exists():
        Subagent(role.split("_")[0], 1)
        time.sleep(3600)
    if os.environ.get("FAKE_CLAUDE_LIMIT_IN") == role and not (RUN_DIR / ".fake_limit_hit").exists():
        hit_usage_limit(role)
    run()


def main() -> None:
    check_invocation(sys.argv[1:])
    open_session(sys.argv[1:])
    brief = json.loads((RUN_DIR / "brief.json").read_text(encoding="utf-8"))
    emit({"type": "system", "subtype": "init", "tools": ["Task", "Bash", "Read", "Write"]})
    exists = lambda *rels: all((RUN_DIR / rel).is_file() for rel in rels)  # noqa: E731
    step("scenariste", exists("scenario.json"), lambda: scenariste(brief))
    step("critique-scenario", exists("scenario_critique_1.json"), lambda: critique_scenario(1))
    if brief.get("max_scenario_iterations", 1) >= 2:
        step("scenariste_2", exists("scenario_critique_2.json"), lambda: scenariste(brief, 2))
        step("critique-scenario_2", exists("scenario_critique_2.json"), lambda: critique_scenario(2))
    step("voix", exists("voice.wav", "words.json", "voice.json"), voix)
    step("monteur", exists("renders/v1.mp4"), lambda: monteur(1))
    step("critique", exists("critique_1.json"), lambda: critique(1))
    iterations = 1
    if brief.get("max_iterations", 1) >= 2:
        step("monteur_2", exists("renders/v2.mp4"), lambda: monteur(2))
        step("critique_2", exists("critique_2.json"), lambda: critique(2))
        iterations = 2
    # Itération 2 : seul le monteur est cité, la voix et le scénario sont réutilisés tels quels.
    step("miniaturiste", exists("thumbnail.json"), lambda: miniaturiste(iterations))
    final = f"renders/v{iterations}.mp4"
    write_json("result.json", {"status": "approved" if iterations == 2 else "max_iterations",
                               "iterations": iterations, "final_video": final, "notes": "faux CLI"})
    emit({"type": "system", "subtype": "permission_denied", "tool_name": "WebFetch", "message": "refusé"})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": "Terminé",
          "num_turns": 12, "total_cost_usd": 0.0})


if __name__ == "__main__":
    main()
