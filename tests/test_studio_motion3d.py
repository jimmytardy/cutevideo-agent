"""Motion design 3D : droit d'abonnement, style auto, politique figée au lancement, outils, bac à sable 3D.

Les rendus réels (WebGL logiciel) exigent Chromium (`playwright install --only-shell chromium`) et bwrap ;
ils sont ignorés sinon. Tout le reste (droits, politique, budget, file du conteneur) est testé partout.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.core.channel_config import resolve_channel_config
from agent.core.subscription import SubscriptionLimits, apply_subscription_caps
from studio import sandbox
from studio.contracts import Brief, allowed_visual_modes, motion3d_enabled
from studio.launcher import REPO_ROOT, build_env, prepare_run_dir
from studio.sandbox import _bwrap_works
from tests.studio_fakes import playwright_chromium_available

needs_render = pytest.mark.skipif(
    not (playwright_chromium_available() and _bwrap_works()),
    reason="Chromium Playwright ou bubblewrap absent (playwright install --only-shell chromium)",
)

# Échoue si WebGL est (in)disponible contrairement à l'attendu, sinon peint une image.
WEBGL_PROBE = """<!doctype html><html><body style="margin:0"><canvas id="c" width="64" height="64"></canvas><script>
const gl = document.createElement("canvas").getContext("webgl2") || new OffscreenCanvas(1, 1).getContext("webgl2");
if (Boolean(gl) !== EXPECTED) throw new Error("webgl=" + Boolean(gl));
const ctx = document.getElementById("c").getContext("2d");
window.renderFrame = async (t) => {
  // navigator.gpu existe en contexte sûr (file://) : seul un adaptateur rendrait WebGPU utilisable.
  if (!EXPECTED && navigator.gpu && await navigator.gpu.requestAdapter()) throw new Error("webgpu utilisable");
  ctx.fillStyle = "#08f"; ctx.fillRect(0, 0, 64, 64);
};
</script></body></html>"""


def _channel(studio: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(config={"studio": studio} if studio else {}, brand_kit=None, theme_category="tech",
                           niche_prompt="", name="t", slug="t", theme_prompt="")


def _run_dir(tmp_path: Path, **brief: object) -> Path:
    return prepare_run_dir(tmp_path / "run", Brief(theme="test", **brief))  # type: ignore[arg-type]


def _tool(run_dir: Path, *args: str, policy: Brief | None = None, **env_overrides: str) -> tuple[int, dict]:
    env = {**build_env(run_dir, policy=policy), "FFMPEG_PRESET": "ultrafast", **env_overrides}
    proc = subprocess.run([sys.executable, "-m", "studio.tools", *args], cwd=run_dir, env=env,
                          capture_output=True, text=True, timeout=900)
    return proc.returncode, json.loads(proc.stdout)


# ── droit et style ────────────────────────────────────────────────────────


@pytest.mark.parametrize("style", ["motion3d", "auto"])
def test_channel_accepts_new_styles(style: str) -> None:
    assert resolve_channel_config(_channel({"visual_style": style})).studio_visual_style == style  # type: ignore[arg-type]


def test_motion3d_right_comes_only_from_subscription() -> None:
    channel = _channel({"visual_style": "motion3d", "motion3d": True})  # une clé de config ne donne aucun droit
    assert resolve_channel_config(channel).studio_motion3d is False  # type: ignore[arg-type]
    paid = resolve_channel_config(channel, subscription_limits=SubscriptionLimits(motion3d_allowed=True))  # type: ignore[arg-type]
    assert paid.studio_motion3d is True and paid.studio_visual_style == "motion3d"


def test_free_plan_downgrades_motion3d_but_keeps_auto() -> None:
    free = SubscriptionLimits()
    assert apply_subscription_caps({"studio": {"visual_style": "motion3d"}}, free)["studio"]["visual_style"] == "animation"
    assert apply_subscription_caps({"studio": {"visual_style": "auto"}}, free)["studio"]["visual_style"] == "auto"
    cfg = resolve_channel_config(_channel({"visual_style": "motion3d"}), subscription_limits=free)  # type: ignore[arg-type]
    assert (cfg.studio_visual_style, cfg.studio_motion3d) == ("animation", False)


@pytest.mark.parametrize(("style", "animations", "allowed", "expected"), [
    ("motion3d", "scripts", True, True),
    ("auto", "templates", True, True),
    ("auto", "scripts", False, False),   # pas de droit
    ("animation", "scripts", True, False),  # droit, mais la chaîne n'a pas choisi la 3D
    ("motion3d", "off", True, False),    # animations coupées
])
def test_motion3d_enabled(style: str, animations: str, allowed: bool, expected: bool) -> None:
    assert motion3d_enabled(style, animations, allowed) is expected


def test_build_brief_enables_3d_only_with_right_and_style() -> None:
    from agent.core.claude_studio import build_brief

    def brief(style: str, right: bool) -> Brief:
        cfg = SimpleNamespace(content_language="fr", short_duration_s=45, words_per_second=3.1,
                              tts_short=SimpleNamespace(voice="", engine=""), tts_voice="v", tts_engine="edge",
                              min_critic_score=80, min_scenario_score=90, max_scenario_iterations=5,
                              editorial_tone="", studio_animations="scripts", studio_visual_style=style,
                              studio_motion3d=right, ai_fallback=SimpleNamespace(enabled=False, max_ai_images_per_video=0))
        ctx = SimpleNamespace(channel_config=cfg, content_plan=None, theme="t", niche_prompt="",
                              target_duration_seconds=30, max_critic_iterations=2, channel=SimpleNamespace(creative_brief=""))
        return build_brief(ctx)  # type: ignore[arg-type]

    assert brief("motion3d", True).motion3d is True
    assert brief("auto", False).motion3d is False
    assert brief("animation", True).motion3d is False


def test_allowed_visual_modes_for_new_styles() -> None:
    assert allowed_visual_modes("motion3d", "scripts") == ("animation", "mixed")
    assert allowed_visual_modes("auto", "scripts") == ("animation", "mixed", "footage")
    assert allowed_visual_modes("motion3d", "off") == ("footage",)


def _validate(tmp_path: Path, intent: str, **env: str) -> dict:
    (tmp_path / "scenario.json").write_text(json.dumps({
        "title": "T", "hook": "H", "beats": [{"text": "Une phrase.", "visual_intent": intent}], "visual_mode": "animation",
    }), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "studio.tools", "validate", "--kind", "scenario", "--path", "scenario.json"],
        cwd=tmp_path, env={**os.environ, "STUDIO_RUN_DIR": str(tmp_path), "STUDIO_ANIMATIONS": "scripts",
                           "PYTHONPATH": str(REPO_ROOT), **env}, capture_output=True, text=True, timeout=120)
    return json.loads(proc.stdout)


def test_validate_requires_a_3d_beat_in_motion3d_style(tmp_path: Path) -> None:
    on = {"STUDIO_VISUAL_STYLE": "motion3d", "STUDIO_MOTION3D": "1"}
    assert "3D" in _validate(tmp_path, "un téléphone", **on)["error"]
    assert _validate(tmp_path, "3D : téléphone et anneau lumineux", **on)["valid"] is True
    assert _validate(tmp_path, "un téléphone", STUDIO_VISUAL_STYLE="auto", STUDIO_MOTION3D="1")["valid"] is True


# ── politique figée au lancement ──────────────────────────────────────────


def test_policy_from_runner_wins_over_edited_brief(tmp_path: Path) -> None:
    """Une reprise relit brief.json, que Claude peut modifier : la 3D ne doit pas s'y obtenir."""
    run_dir = _run_dir(tmp_path, visual_style="motion3d", motion3d=False)
    forged = json.loads((run_dir / "brief.json").read_text(encoding="utf-8")) | {"motion3d": True}
    (run_dir / "brief.json").write_text(json.dumps(forged), encoding="utf-8")
    assert build_env(run_dir)["STUDIO_MOTION3D"] == "1"  # sans politique (studio.run), le fichier fait foi…
    policy = Brief(theme="test", visual_style="motion3d", motion3d=False)
    env = build_env(run_dir, policy=policy)
    assert env["STUDIO_MOTION3D"] == "0"  # … mais le runner passe toujours la sienne
    assert env["BASH_DEFAULT_TIMEOUT_MS"] == "1200000"
    assert build_env(run_dir, policy=Brief(theme="t", motion3d=True))["BASH_DEFAULT_TIMEOUT_MS"] == "1800000"


def test_3d_tools_refused_without_right(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    (run_dir / "anim" / "x.html").write_text(WEBGL_PROBE, encoding="utf-8")
    code, out = _tool(run_dir, "animate-template", "--template", "phone3d", "--params", "{}", "--duration", "1",
                      "--name", "x")
    assert code == 1 and "phone3d" not in out["error"].split("disponibles")[1]  # modèles 3D masqués
    code, out = _tool(run_dir, "animate", "--3d", "--script", "anim/x.html", "--duration", "1", "--name", "x")
    assert code == 1 and "3D non disponible" in out["error"]


def test_3d_budget_and_clip_length(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, visual_style="motion3d", motion3d=True)
    (run_dir / "anim" / "x.html").write_text(WEBGL_PROBE, encoding="utf-8")
    code, out = _tool(run_dir, "animate", "--3d", "--script", "anim/x.html", "--duration", "9", "--name", "x")
    assert code == 1 and "≤ 7 s" in out["error"]
    (run_dir / "anim" / ".motion3d.json").write_text(json.dumps({"01_hook": 7, "04_chiffre": 7, "07_fin": 5}))
    code, out = _tool(run_dir, "animate", "--3d", "--script", "anim/x.html", "--duration", "3", "--name", "x")
    assert code == 1 and "budget 3D" in out["error"]
    # Refaire un plan existant sous le même nom ne compte pas deux fois : 7 + 7 + 5 → 7 + 7 + 6 reste sous 20 s.
    code, out = _tool(run_dir, "animate-template", "--template", "number3d", "--params", "{}", "--duration", "6",
                      "--name", "07_fin", STUDIO_SANDBOX="container", STUDIO_SANDBOX_QUEUE_WAIT_S="0")
    assert code == 1 and "budget" not in out["error"] and "studio-sandbox-3d" in out["error"]
    # Rendu en échec : la réservation est rendue, l'ancienne durée du plan reste comptée…
    assert json.loads((run_dir / "anim" / ".motion3d.json").read_text())["07_fin"] == 5
    # … et un nouveau plan en échec ne laisse aucune trace.
    code, out = _tool(run_dir, "animate-template", "--template", "phone3d", "--params", "{}", "--duration", "1",
                      "--name", "08_neuf", STUDIO_SANDBOX="container", STUDIO_SANDBOX_QUEUE_WAIT_S="0")
    assert code == 1 and "08_neuf" not in json.loads((run_dir / "anim" / ".motion3d.json").read_text())


def test_render_timeout_grows_with_frames_and_is_capped() -> None:
    assert sandbox.render_timeout(10_000, webgl=False) == sandbox.DEFAULT_TIMEOUT_S
    assert sandbox.render_timeout(60, webgl=True) == pytest.approx(60 + 60 * sandbox.SECONDS_PER_FRAME_3D)
    assert sandbox.render_timeout(10_000, webgl=True) == sandbox.MAX_3D_TIMEOUT_S


# ── file du conteneur : file 3D séparée, délai en deux temps, annulation ──


def test_3d_jobs_use_their_own_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_SANDBOX_JOBS_DIR", str(tmp_path / ".sandbox-jobs"))
    assert sandbox.jobs_dir() == tmp_path / ".sandbox-jobs"
    assert sandbox.jobs_dir(webgl=True) == tmp_path / ".sandbox-jobs-3d"


def _queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    jobs = tmp_path / ".sandbox-jobs"
    monkeypatch.setenv("STUDIO_SANDBOX_JOBS_DIR", str(jobs))
    monkeypatch.setattr(sandbox, "RESULT_MARGIN_S", 0.0)
    return jobs


def test_queue_wait_does_not_eat_render_time_and_abandon_cancels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Le délai de rendu part de la prise en charge ; un job pris puis abandonné laisse un `.cancel` au worker."""
    jobs = _queue(tmp_path, monkeypatch)

    async def run() -> None:
        task = asyncio.create_task(sandbox._run_container({"webgl": False}, timeout_s=0.5))
        await asyncio.sleep(1.5)
        assert not task.done()  # toujours en file au-delà du délai de rendu : il ne court pas encore
        (pending,) = jobs.glob("*.json")
        pending.rename(pending.with_suffix(".running"))  # le worker prend le job… puis ne répond pas
        with pytest.raises(sandbox.SandboxError, match="délai dépassé"):
            await task

    asyncio.run(run())
    assert len(list(jobs.glob("*.cancel"))) == 1


def test_job_never_picked_is_withdrawn_without_cancel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _queue(tmp_path, monkeypatch)
    monkeypatch.setattr(sandbox, "QUEUE_WAIT_S", 0.3)
    with pytest.raises(sandbox.SandboxError, match="pas pris le job"):
        asyncio.run(sandbox._run_container({"webgl": True}, timeout_s=10))
    queue = tmp_path / ".sandbox-jobs-3d"
    assert not list(queue.iterdir())  # ni job en attente, ni `.cancel` que personne ne lirait


def test_cancelled_tool_cancels_the_running_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Outil tué (SIGTERM → annulation de la tâche) : le worker est prévenu."""
    jobs = _queue(tmp_path, monkeypatch)

    async def run() -> None:
        task = asyncio.create_task(sandbox._run_container({"webgl": False}, timeout_s=60))
        await asyncio.sleep(0.3)
        (pending,) = jobs.glob("*.json")
        pending.rename(pending.with_suffix(".running"))
        await asyncio.sleep(0.8)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert len(list(jobs.glob("*.cancel"))) == 1


def test_worker_sweeps_stale_markers(tmp_path: Path) -> None:
    jobs = tmp_path / "runs" / ".sandbox-jobs"
    jobs.mkdir(parents=True)
    for name in ("old.cancel", "old.done", "fresh.done", "busy.cancel", "busy.running"):
        (jobs / name).touch()
    old = time.time() - 7200
    for name in ("old.cancel", "old.done", "busy.cancel"):
        os.utime(jobs / name, (old, old))
    code = "import sys; sys.path.insert(0, %r); import sandbox_worker as w; w.sweep_stale_markers()"
    subprocess.run([sys.executable, "-c", code % str(REPO_ROOT / "studio")], check=True,
                   env={**os.environ, "STUDIO_SANDBOX_JOBS_DIR": str(jobs)})
    assert sorted(p.name for p in jobs.iterdir()) == ["busy.cancel", "busy.running", "fresh.done"]


def test_worker_gives_up_before_the_producer() -> None:
    """Le worker (autonome, sans import du repo) doit expirer avant que le producteur n'abandonne le job."""
    sys.path.insert(0, str(REPO_ROOT / "studio"))
    try:
        import sandbox_worker
    finally:
        sys.path.pop(0)
    assert sandbox_worker.KILL_MARGIN_S < sandbox.RESULT_MARGIN_S


def test_worker_stops_a_cancelled_job(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    jobs = runs / ".sandbox-jobs-3d"
    out = runs / "p" / "out"
    for d in (jobs, out):
        d.mkdir(parents=True)
    script = runs / "p" / "sleep.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    (jobs / "j1.json").write_text(json.dumps({"kind": "python", "script": str(script), "out_dir": str(out),
                                              "width": 8, "height": 8, "fps": 1, "duration": 1, "timeout_s": 120}))
    code = "import sys; sys.path.insert(0, %r); import sandbox_worker as w; from pathlib import Path; w.handle(Path(%r))"
    proc = subprocess.Popen([sys.executable, "-c", code % (str(REPO_ROOT / "studio"), str(jobs / "j1.json"))],
                            env={**os.environ, "STUDIO_SANDBOX_JOBS_DIR": str(jobs)})
    time.sleep(2)
    (jobs / "j1.cancel").touch()
    assert proc.wait(timeout=20) == 0
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result == {"ok": False, "error": "rendu annulé par l'outil"}
    assert not list(jobs.iterdir())  # ni .running, ni .cancel, ni .done orphelin


# ── rendus réels ──────────────────────────────────────────────────────────


@needs_render
@pytest.mark.parametrize(("three_d", "expected"), [(False, "false"), (True, "true")])
def test_webgl_exists_only_for_3d_renders(tmp_path: Path, three_d: bool, expected: str) -> None:
    run_dir = _run_dir(tmp_path, visual_style="motion3d", motion3d=True)
    (run_dir / "anim" / "probe.html").write_text(WEBGL_PROBE.replace("EXPECTED", expected), encoding="utf-8")
    args = ["animate", "--script", "anim/probe.html", "--duration", "0.5", "--name", "probe"]
    code, out = _tool(run_dir, *args, *(["--3d"] if three_d else []), STUDIO_SANDBOX="bwrap")
    assert code == 0, out


@needs_render
def test_number3d_preview_then_render(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, visual_style="motion3d", motion3d=True)
    # Paramètre mal nommé : erreur claire au lieu d'un « 0 » rendu en silence.
    code, out = _tool(run_dir, "animate-template", "--template", "number3d", "--params", '{"value": 42}',
                      "--duration", "1", "--name", "n", "--preview", STUDIO_SANDBOX="bwrap")
    assert code == 1 and "« to »" in out["error"], out
    params = json.dumps({"title": "RECORD", "to": 23, "suffix": " %"})
    code, out = _tool(run_dir, "animate-template", "--template", "number3d", "--params", params, "--duration", "1",
                      "--name", "n", "--preview", STUDIO_SANDBOX="bwrap")
    assert code == 0, out
    assert (run_dir / out["preview"]).is_file() and out["frames"] == 6 and out["estimated_render_min"] > 0
    assert not (run_dir / "media" / "anim_n.mp4").exists()
    assert not (run_dir / "anim" / ".motion3d.json").exists()  # un aperçu ne consomme pas le budget
    code, out = _tool(run_dir, "animate-template", "--template", "number3d", "--params", params, "--duration", "0.5",
                      "--name", "n", STUDIO_SANDBOX="bwrap")
    assert code == 0, out
    assert json.loads((run_dir / "anim" / ".motion3d.json").read_text()) == {"n": 0.5}


# Une scène 3D ne voit que son dossier anim/ (origine fictive servie par sandbox_exec) : ni remontée, ni lien
# symbolique sortant, ni réseau.
ESCAPE_3D = """<!doctype html><html><body><script>
const ok = async (u) => { try { return (await fetch(u)).ok; } catch (e) { return false; } };
window.renderFrame = async () => {
  if (!(await ok("lib/studio.js"))) throw new Error("anim/ doit rester lisible");
  for (const u of ["../brief.json", "%2e%2e/brief.json", "dehors.json", "http://example.com/"]) {
    if (await ok(u)) throw new Error("accès hors de anim/ : " + u);
  }
};
</script></body></html>"""


@needs_render
def test_3d_scene_cannot_read_outside_anim(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, visual_style="motion3d", motion3d=True)
    (run_dir / "anim" / "dehors.json").symlink_to(run_dir / "brief.json")
    (run_dir / "anim" / "escape.html").write_text(ESCAPE_3D, encoding="utf-8")
    code, out = _tool(run_dir, "animate", "--3d", "--script", "anim/escape.html", "--duration", "0.5", "--name", "e",
                      STUDIO_SANDBOX="bwrap")
    assert code == 0, out
