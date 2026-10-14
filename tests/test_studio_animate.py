"""Animations Claude Studio : politique par chaîne, modèles, scripts jetables et bac à sable.

Les rendus nécessitent Chromium (`playwright install --only-shell chromium`) et bwrap ;
ils sont ignorés sinon. La politique (off / templates / scripts) est testée partout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from studio.contracts import Brief
from studio.launcher import REPO_ROOT, build_env, prepare_run_dir
from studio.sandbox import _bwrap_works
from tests.studio_fakes import playwright_chromium_available

needs_render = pytest.mark.skipif(
    not playwright_chromium_available(), reason="Chromium Playwright absent (playwright install --only-shell chromium)"
)
needs_bwrap = pytest.mark.skipif(not _bwrap_works(), reason="bubblewrap indisponible")

HTML_SCRIPT = """<!doctype html><html><body style="margin:0;background:#000">
<canvas id="c" width="1080" height="1920"></canvas><script>
const ctx = document.getElementById("c").getContext("2d");
window.renderFrame = (t) => { ctx.fillStyle = `rgb(${Math.round(255 * t)},0,0)`; ctx.fillRect(0, 0, 1080, 1920); };
</script></body></html>"""

PY_SCRIPT = """import os
from PIL import Image
out, n = os.environ["OUT_DIR"], int(float(os.environ["DURATION"]) * int(os.environ["FPS"]))
for i in range(n):
    Image.new("RGB", (int(os.environ["WIDTH"]), int(os.environ["HEIGHT"])), (0, 0, 200)).save(f"{out}/frame_{i:05d}.png")
"""

# Ce que le bac à sable doit empêcher : lire les secrets, le repo, et sortir sur le réseau.
ESCAPE_SCRIPT = """import os, socket
from PIL import Image
out = os.environ["OUT_DIR"]
report = {"env_key": any(k in os.environ for k in ("ANTHROPIC_API_KEY", "STUDIO_GEMINI_API_KEY", "STUDIO_FAL_KEY")), "repo_env": os.path.exists(%r), "network": False}
try:
    socket.create_connection(("1.1.1.1", 80), timeout=3); report["network"] = True
except OSError:
    pass
Image.new("RGB", (64, 64)).save(f"{out}/frame_00000.png")
open(f"{out}/report.json", "w").write(__import__("json").dumps(report))
""" % str(REPO_ROOT / ".env")


def _run_dir(tmp_path: Path, animations: str = "scripts") -> Path:
    return prepare_run_dir(tmp_path / "run", Brief(theme="test", animations=animations))  # type: ignore[arg-type]


def _tool(run_dir: Path, *args: str, **env_overrides: str) -> tuple[int, dict]:
    env = {**build_env(run_dir), "FFMPEG_PRESET": "ultrafast", **env_overrides}
    proc = subprocess.run([sys.executable, "-m", "studio.tools", *args], cwd=run_dir, env=env,
                          capture_output=True, text=True, timeout=600)
    return proc.returncode, json.loads(proc.stdout)


def _probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    return data["streams"][0]["width"], data["streams"][0]["height"], float(data["format"]["duration"])


# ── politique ─────────────────────────────────────────────────────────────


def test_launcher_passes_brief_policy_and_copies_libs(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, "templates")
    assert build_env(run_dir)["STUDIO_ANIMATIONS"] == "templates"
    assert (run_dir / "anim" / "lib" / "gsap.min.js").is_file()
    assert (run_dir / "anim" / "lib" / "d3.min.js").is_file()
    # Claude peut réécrire brief.json, mais la variable est figée au lancement.
    (run_dir / "brief.json").write_text("{corrompu", encoding="utf-8")
    assert build_env(run_dir)["STUDIO_ANIMATIONS"] == "off"


def test_channel_config_default_and_override() -> None:
    from agent.core.channel_config import resolve_channel_config

    def channel(config: dict) -> SimpleNamespace:
        return SimpleNamespace(config=config, brand_kit=None, theme_category="sciences", niche_prompt="",
                               name="t", slug="t", theme_prompt="")

    assert resolve_channel_config(channel({})).studio_animations == "scripts"
    assert resolve_channel_config(channel({"studio": {"animations": "off"}})).studio_animations == "off"
    assert resolve_channel_config(channel({"studio": {"animations": "nimporte"}})).studio_animations == "scripts"


def test_build_brief_carries_channel_policy() -> None:
    from agent.core.claude_studio import build_brief

    cfg = SimpleNamespace(content_language="fr", short_duration_s=45, tts_short=SimpleNamespace(voice="", engine=""),
                          tts_voice="v", tts_engine="edge", quality_max_iterations=2, min_critic_score=80,
                          editorial_tone="", studio_animations="templates",
                          ai_fallback=SimpleNamespace(enabled=False, max_ai_images_per_video=10))
    ctx = SimpleNamespace(channel_config=cfg, content_plan=None, theme="t", niche_prompt="",
                          target_duration_seconds=30, max_critic_iterations=2,
                          channel=SimpleNamespace(creative_brief="  Pas de sensationnalisme.  "))
    brief = build_brief(ctx)  # type: ignore[arg-type]
    assert brief.animations == "templates"
    assert brief.creative_brief == "Pas de sensationnalisme."
    assert brief.max_ai_images == 0


@pytest.mark.parametrize(("policy", "args"), [
    ("off", ("animate-template", "--template", "title", "--params", "{}", "--duration", "1", "--name", "x")),
    ("templates", ("animate", "--script", "anim/x.html", "--duration", "1", "--name", "x")),
])
def test_policy_is_enforced_by_tools(tmp_path: Path, policy: str, args: tuple[str, ...]) -> None:
    run_dir = _run_dir(tmp_path, policy)
    (run_dir / "anim" / "x.html").write_text(HTML_SCRIPT, encoding="utf-8")
    code, out = _tool(run_dir, *args)
    assert code == 1
    assert "non autorisées" in out["error"]


def test_script_must_live_in_anim_dir(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    (run_dir / "evil.html").write_text(HTML_SCRIPT, encoding="utf-8")
    code, out = _tool(run_dir, "animate", "--script", "evil.html", "--duration", "1", "--name", "x")
    assert code == 1 and "anim/" in out["error"]


# ── rendus ────────────────────────────────────────────────────────────────


@needs_render
def test_template_renders_vertical_clip_with_credit(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, "templates")
    code, out = _tool(run_dir, "animate-template", "--template", "counter", "--duration", "1.5", "--name", "01_n",
                      "--params", json.dumps({"to": 384400, "suffix": " km", "label": "Terre-Lune"}))
    assert code == 0, out
    assert out["media"] == "media/anim_01_n.mp4"
    width, height, duration = _probe(run_dir / out["media"])
    assert (width, height) == (1080, 1920)
    assert duration == pytest.approx(1.5, abs=0.1)
    assert (run_dir / out["sheet"]).is_file()
    credit = json.loads((run_dir / "media" / "credits.json").read_text())["media/anim_01_n.mp4"]
    assert credit["license"] == "original" and credit["template"] == "counter"


@needs_render
@needs_bwrap
@pytest.mark.parametrize(("filename", "content"), [("02_rouge.html", HTML_SCRIPT), ("03_bleu.py", PY_SCRIPT)])
def test_disposable_scripts_render_in_bwrap(tmp_path: Path, filename: str, content: str) -> None:
    run_dir = _run_dir(tmp_path)
    (run_dir / "anim" / filename).write_text(content, encoding="utf-8")
    name = Path(filename).stem
    code, out = _tool(run_dir, "animate", "--script", f"anim/{filename}", "--duration", "1", "--name", name,
                      STUDIO_SANDBOX="bwrap")
    assert code == 0, out
    assert _probe(run_dir / out["media"])[:2] == (1080, 1920)


@needs_render
@needs_bwrap
def test_script_errors_are_reported_to_claude(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    (run_dir / "anim" / "bug.html").write_text("<script>window.renderFrame = () => { boom(); };</script>",
                                               encoding="utf-8")
    code, out = _tool(run_dir, "animate", "--script", "anim/bug.html", "--duration", "0.5", "--name", "bug",
                      STUDIO_SANDBOX="bwrap")
    assert code == 1 and "boom" in out["error"]


@needs_bwrap
def test_bwrap_sandbox_blocks_secrets_repo_and_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from studio.sandbox import run_sandboxed

    anim = tmp_path / "anim"
    anim.mkdir()
    (anim / "escape.py").write_text(ESCAPE_SCRIPT, encoding="utf-8")
    monkeypatch.setenv("STUDIO_SANDBOX", "bwrap")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret")
    monkeypatch.setenv("STUDIO_GEMINI_API_KEY", "g-test-secret")
    monkeypatch.setenv("STUDIO_FAL_KEY", "fal-test-secret")
    asyncio.run(run_sandboxed("python", anim / "escape.py", anim, tmp_path / "out", width=64, height=64, fps=2,
                              duration=0.5))
    report = json.loads((tmp_path / "out" / "frames" / "report.json").read_text())
    assert report == {"env_key": False, "repo_env": False, "network": False}


@needs_render
def test_container_protocol_with_local_worker(tmp_path: Path) -> None:
    """Mode Docker : le job passe par la file de fichiers lue par `sandbox_worker.py`."""
    runs = tmp_path / "runs"
    run_dir = prepare_run_dir(runs / "p1", Brief(theme="t"))
    (run_dir / "anim" / "02_rouge.html").write_text(HTML_SCRIPT, encoding="utf-8")
    jobs = runs / ".sandbox-jobs"
    worker = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "studio" / "sandbox_worker.py")],
        env={**os.environ, "STUDIO_SANDBOX_JOBS_DIR": str(jobs),
             "PLAYWRIGHT_BROWSERS_PATH": os.getenv("PLAYWRIGHT_BROWSERS_PATH",
                                                   str(Path.home() / ".cache" / "ms-playwright"))},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        code, out = _tool(run_dir, "animate", "--script", "anim/02_rouge.html", "--duration", "0.5", "--name", "r",
                          STUDIO_SANDBOX="container", STUDIO_SANDBOX_JOBS_DIR=str(jobs))
    finally:
        worker.terminate()
        worker.wait(timeout=10)
    assert code == 0, out
    assert _probe(run_dir / out["media"])[:2] == (1080, 1920)
    assert not list(jobs.glob("*.json")) and not list(jobs.glob("*.done"))


def test_container_worker_rejects_paths_outside_runs(tmp_path: Path) -> None:
    jobs = tmp_path / "runs" / ".sandbox-jobs"
    jobs.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (jobs / "j1.json").write_text(json.dumps({"kind": "python", "script": "/etc/passwd", "out_dir": str(outside)}))
    code = "import sys; sys.path.insert(0, %r); import sandbox_worker as w; from pathlib import Path; w.handle(Path(%r))"
    proc = subprocess.run(
        [sys.executable, "-c", code % (str(REPO_ROOT / "studio"), str(jobs / "j1.json"))],
        env={**os.environ, "STUDIO_SANDBOX_JOBS_DIR": str(jobs)}, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert (jobs / "j1.done").exists()  # le producteur est débloqué…
    assert not list(outside.iterdir())  # … sans rien écrire hors du volume des runs


def test_render_waits_then_refuses_when_machine_is_low_on_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from studio import sandbox

    monkeypatch.setattr(sandbox, "available_memory_mb", lambda: 300)
    with pytest.raises(sandbox.SandboxError, match="mémoire insuffisante"):
        asyncio.run(sandbox.wait_for_memory(min_free_mb=1200, timeout_s=0))
    monkeypatch.setattr(sandbox, "available_memory_mb", lambda: 4000)
    asyncio.run(sandbox.wait_for_memory(min_free_mb=1200, timeout_s=0))


@needs_bwrap
def test_bwrap_sandbox_is_memory_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un script gourmand est tué dans son cgroup, sans OOM global de la machine."""
    import asyncio

    from studio import sandbox

    if not sandbox._cgroup_scope_works():
        pytest.skip("systemd-run --user indisponible")
    anim = tmp_path / "anim"
    anim.mkdir()
    (anim / "hog.py").write_text("b = bytearray(1500 * 1024 * 1024)\n", encoding="utf-8")
    monkeypatch.setenv("STUDIO_SANDBOX", "bwrap")
    monkeypatch.setattr(sandbox, "MEMORY_MAX", "300M")
    with pytest.raises(sandbox.SandboxError):
        asyncio.run(sandbox.run_sandboxed("python", anim / "hog.py", anim, tmp_path / "out", width=64, height=64,
                                          fps=1, duration=1))
