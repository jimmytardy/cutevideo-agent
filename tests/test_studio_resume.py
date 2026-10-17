"""Reprise d'une création après un redémarrage du worker (agent/core/studio_resume.py).

Les tests unitaires tournent toujours ; le scénario de bout en bout (Orchestrator → runner → Postgres/Redis,
faux CLI) exige la même infra de TEST jetable que `tests/test_studio_pipeline_db.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core import studio_resume
from agent.core.claude_studio import ClaudeStudioRunner
from agent.core.studio_resume import decide, paused_until, record_pause, usage_limit_reset
from studio.launcher import ClaudeRunError, LaunchConfig, StreamParser, build_command
from tests.studio_fakes import install_fake_claude

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_URL = os.getenv("CUTEVIDEO_TEST_DATABASE_URL")
REDIS_URL = os.getenv("CUTEVIDEO_TEST_REDIS_URL")


def test_decide_fresh_when_nothing_to_resume() -> None:
    assert decide(None, progress=0, run_dir_ok=True).action == "fresh"
    assert decide({"session_id": "s"}, progress=0, run_dir_ok=False).action == "fresh"  # run dir purgé


def test_decide_counts_consecutive_resumes_and_gives_up(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_MAX_RESUMES", "3")
    state: dict = {"session_id": "s"}
    for attempt in (1, 2, 3):
        decision = decide(state, progress=2, run_dir_ok=True)
        assert decision.action == "resume" and decision.state["resumes"] == attempt
        state = decision.state
    decision = decide(state, progress=2, run_dir_ok=True)
    assert decision.action == "give_up" and "3 interruptions sans progrès" in decision.reason


def test_decide_progress_resets_counter_but_total_is_capped(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_MAX_RESUMES", "3")
    monkeypatch.setenv("STUDIO_MAX_RESUMES_TOTAL", "4")
    state: dict = {"session_id": "s", "resumes": 3, "progress": 1}
    decision = decide(state, progress=2, run_dir_ok=True)  # une étape réussie depuis : on repart à 1
    assert decision.action == "resume" and decision.state["resumes"] == 1
    state = {**decision.state, "total_resumes": 4}
    assert decide(state, progress=3, run_dir_ok=True).action == "give_up"


def test_decide_zero_disables_resume(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_MAX_RESUMES", "0")
    assert decide({"session_id": "s"}, progress=0, run_dir_ok=True).action == "give_up"


def test_build_command_session_flags() -> None:
    cfg = LaunchConfig(model="m", claude_bin="claude")
    fresh = build_command(cfg, session_id="abc")
    assert fresh[fresh.index("--session-id") + 1] == "abc" and "--no-session-persistence" not in fresh
    resumed = build_command(cfg, "Reprends", session_id="abc", resume=True)
    assert resumed[1:3] == ["-p", "Reprends"] and resumed[resumed.index("--resume") + 1] == "abc"
    assert "--session-id" not in resumed
    assert "--no-session-persistence" in build_command(cfg)


def test_claude_run_error_no_turn_played() -> None:
    assert ClaudeRunError("x", result={"is_error": True, "num_turns": 0}).no_turn_played
    assert not ClaudeRunError("x", result={"is_error": True, "num_turns": 5}).no_turn_played
    # Sortie sans résultat (crash, processus tué) : pas une session introuvable, pas de nouvelle session complète.
    assert not ClaudeRunError("x").no_turn_played


def _successes(runs: list[list], *names: str) -> list[int]:
    """Nombre d'étapes réussies par rôle (une reprise ne doit pas refaire les étapes déjà faites)."""
    done = [name for name, status, _ in runs if status == "success"]
    return [done.count(name) for name in names]


EARLY_STEPS = ("scenario_agent", "scenario_critic_agent", "narrator_agent")


NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _limit_error(text: str = "erreur", *, status: str | None = None, resets_at: int | None = None) -> ClaudeRunError:
    rate_limit = {"status": status, "resetsAt": resets_at} if status else None
    return ClaudeRunError(text, result={"is_error": True, "num_turns": 4, "result": text}, rate_limit=rate_limit)


def test_usage_limit_reset_from_rate_limit_event() -> None:
    reset = int((NOW + timedelta(hours=2)).timestamp())
    until = usage_limit_reset(_limit_error(status="rejected", resets_at=reset), now=NOW)
    assert until == NOW + timedelta(hours=2, seconds=60)


def test_usage_limit_reset_from_message_and_defaults(monkeypatch) -> None:
    reset = int((NOW + timedelta(minutes=30)).timestamp())
    assert usage_limit_reset(_limit_error(f"Claude AI usage limit reached|{reset}"), now=NOW) == (
        NOW + timedelta(minutes=30, seconds=60)
    )
    # Reset déjà passé : jamais de reprise immédiate en boucle.
    past = int((NOW - timedelta(hours=1)).timestamp())
    assert usage_limit_reset(_limit_error(status="rejected", resets_at=past), now=NOW) == NOW + timedelta(seconds=120)
    monkeypatch.setenv("STUDIO_LIMIT_DEFAULT_WAIT_S", "900")
    assert usage_limit_reset(_limit_error("You've hit your limit"), now=NOW) == NOW + timedelta(seconds=900)
    assert usage_limit_reset(_limit_error("contrat invalide"), now=NOW) is None
    # Faux positifs : « 429 » ou « limit reached » ailleurs (stderr, budget) ne sont pas une limite d'usage.
    assert usage_limit_reset(_limit_error("budget limit reached at line 429"), now=NOW) is None
    in_errors = ClaudeRunError("x", result={"is_error": True, "num_turns": 2, "errors": ["429 rate_limit_error"]})
    assert usage_limit_reset(in_errors, now=NOW) == NOW + timedelta(seconds=900)  # STUDIO_LIMIT_DEFAULT_WAIT_S (900 ci-dessus)
    stderr_only = ClaudeRunError("Claude s'est arrêté sans résultat : usage limit dans un log", result=None)
    assert usage_limit_reset(stderr_only, now=NOW) is None
    assert usage_limit_reset(_limit_error("x", status="allowed", resets_at=past), now=NOW) is None


def test_record_pause_is_capped(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_MAX_LIMIT_PAUSES", "2")
    state: dict = {"session_id": "s"}
    for expected in (True, True, False):
        allowed, state = record_pause(state, NOW)
        assert allowed is expected
    assert state["limit_pauses"] == 3 and paused_until(state) == NOW


@pytest.fixture
def pausing_runner(monkeypatch, tmp_path: Path):
    """Runner isolé de la base : collaborateurs DB/Redis remplacés, recorder factice (le fixture e2e couvre la base)."""
    monkeypatch.setenv("STUDIO_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(studio_resume, "set_user_limit", AsyncMock())
    ctx = SimpleNamespace(project_id=uuid.uuid4(), channel=SimpleNamespace(user_id=uuid.uuid4()))
    runner = ClaudeStudioRunner(ctx)
    monkeypatch.setattr(runner, "_save_session_state", AsyncMock())
    monkeypatch.setattr(runner, "_forget_session", MagicMock())
    monkeypatch.setattr(runner, "_fail_open_runs", AsyncMock())
    recorder = SimpleNamespace(close_dangling=AsyncMock(), mark_limit_interrupted=AsyncMock())
    return runner, recorder, tmp_path / "cfg"


@pytest.mark.asyncio
async def test_pause_in_run_fails_open_steps_at_cap(monkeypatch, pausing_runner) -> None:
    monkeypatch.setenv("STUDIO_MAX_LIMIT_PAUSES", "0")
    runner, recorder, cfg = pausing_runner
    with pytest.raises(ClaudeRunError, match="1 fois"):
        await runner._pause(NOW + timedelta(hours=1), {"session_id": "s"}, cfg, recorder=recorder)
    recorder.close_dangling.assert_awaited_once()
    assert recorder.close_dangling.await_args.args[0] == "failed"
    recorder.mark_limit_interrupted.assert_not_awaited()
    runner._fail_open_runs.assert_awaited_once()  # étapes `interrupted` d'une pause précédente aussi
    runner._save_session_state.assert_awaited_once_with(None)
    runner._forget_session.assert_called_once()
    studio_resume.set_user_limit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pause_in_run_interrupts_open_steps_when_pause_granted(monkeypatch, pausing_runner) -> None:
    monkeypatch.setenv("STUDIO_MAX_LIMIT_PAUSES", "6")
    runner, recorder, cfg = pausing_runner
    with pytest.raises(studio_resume.StudioPaused):
        await runner._pause(NOW + timedelta(hours=1), {"session_id": "s"}, cfg, recorder=recorder)
    recorder.close_dangling.assert_awaited_once_with("interrupted", studio_resume.LIMIT_MESSAGE)
    recorder.mark_limit_interrupted.assert_awaited_once()
    runner._fail_open_runs.assert_not_awaited()
    assert runner._save_session_state.await_args.args[0]["limit_pauses"] == 1
    studio_resume.set_user_limit.assert_awaited_once()


def test_decide_after_pause_does_not_count_as_worker_resume(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_MAX_RESUMES", "3")
    state = {"session_id": "s", "resumes": 3, "progress": 2, "paused_until": NOW.isoformat(), "limit_pauses": 1}
    decision = decide(state, progress=2, run_dir_ok=True)
    assert decision.action == "resume" and decision.state["resumes"] == 3
    assert "paused_until" not in decision.state and decision.state["limit_pauses"] == 1
    # Progression notée : un redémarrage de worker sans nouvelle étape ne remet pas le compteur à zéro.
    assert decision.state["progress"] == 2
    assert decide(decision.state, progress=2, run_dir_ok=True).action == "give_up"  # 4e reprise sans progrès


def test_stream_parser_keeps_last_rate_limit() -> None:
    parser = StreamParser()
    for status in ("allowed", "rejected"):
        parser.feed(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": status, "resetsAt": 1}}))
    assert parser.rate_limit == {"status": "rejected", "resetsAt": 1}


@pytest.mark.skipif(
    not (DB_URL and REDIS_URL),
    reason="CUTEVIDEO_TEST_DATABASE_URL et CUTEVIDEO_TEST_REDIS_URL requis (infra de test jetable)",
)
def test_worker_restart_resumes_creation(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": DB_URL or "",
        "REDIS_URL": REDIS_URL or "",
        "CLAUDE_BIN": str(install_fake_claude(tmp_path / "bin")),
        "STUDIO_RUNS_DIR": str(tmp_path / "runs"),
        "FFMPEG_PRESET": "ultrafast",
        "PYTHONPATH": str(REPO_ROOT),
    }
    migrate = subprocess.run(
        [str(Path(sys.executable).with_name("alembic")), "upgrade", "head"],
        cwd=REPO_ROOT, env={k: v for k, v in env.items() if k != "PYTHONPATH"}, capture_output=True, text=True,
    )
    assert migrate.returncode == 0, migrate.stderr[-3000:]
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tests" / "fixtures" / "studio_db_resume.py")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=1500,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    facts = json.loads(proc.stdout.strip().splitlines()[-1])

    interrupted = facts["interrupted"]
    assert interrupted["status"] == "running" and interrupted["error"] == "Worker redémarré — reprise automatique"
    assert ["editor_agent", "interrupted", 1] in interrupted["runs"]
    assert interrupted["session"]["session_id"] and interrupted["transcripts"] == 1
    assert interrupted["scenario_kept"]

    assert facts["resume"] == {"reconciled": 1, "payload_resume": True, "error": None}
    resumed = facts["resumed"]
    assert resumed["status"] == "approved" and resumed["error"] is None and resumed["session"] is None
    assert _successes(resumed["runs"], *EARLY_STEPS) == _successes(interrupted["runs"], *EARLY_STEPS)  # rien de refait
    assert _successes(resumed["runs"], "critic_agent") == [2]  # la boucle d'itération continue normalement
    assert resumed["transcripts"] == 0 and not resumed["resume_file"]

    fallback = facts["fallback"]
    assert fallback["error"] is None and fallback["status"] == "approved"
    assert _successes(fallback["runs"], *EARLY_STEPS) == _successes(facts["fallback_before"], *EARLY_STEPS)

    give_up = facts["give_up"]
    assert give_up["status"] == "failed" and "abandonnée" in (give_up["error"] or "")
    assert give_up["reconciled_after"] == 0

    limit = facts["limit"]
    paused = limit["paused"]
    assert paused["status"] == "paused" and "Limite d'usage Claude atteinte" in paused["error"]
    assert paused["session"]["limit_pauses"] == 1 and paused["session"]["paused_until"]
    assert ["editor_agent", "interrupted", 1] in paused["runs"]
    assert paused["transcripts"] == 1 and paused["user_limit"]  # session gardée, autres projets prévenus
    sibling = limit["sibling"]
    assert sibling["status"] == "paused" and sibling["runs"] == [] and not sibling["run_dir"]  # Claude pas appelé
    capped = limit["capped"]
    assert capped["status"] == "failed" and "7 fois" in (capped["raised"] or "")
    assert limit["requeued"] == 1
    resumed = limit["resumed"]
    assert resumed["payload_resume"] is True and resumed["status"] == "approved" and resumed["session"] is None
    assert _successes(resumed["runs"], *EARLY_STEPS) == _successes(paused["runs"], *EARLY_STEPS)  # rien de refait
    api_key = limit["api_key"]
    assert api_key["status"] == "failed" and "usage limit" in (api_key["raised"] or "")
    capped_in_run = limit["capped_in_run"]  # plafond atteint pendant la création : rien ne reste « interrupted »
    assert capped_in_run["status"] == "failed" and "1 fois" in (capped_in_run["raised"] or "")
    assert ["editor_agent", "failed", 1] in capped_in_run["runs"]
    assert not [run for run in capped_in_run["runs"] if run[1] == "interrupted"]
    assert capped_in_run["session"] is None and capped_in_run["transcripts"] == 0


def test_usage_limit_reset_real_claude_code_shapes() -> None:
    """Formes observées avec `claude -p` (anthropics/claude-code#57096, doc d'erreurs de Claude Code)."""
    reset = int((NOW + timedelta(hours=1)).timestamp())
    # `result` vide, limite portée par le message assistant synthétique et le rate_limit_event refusé.
    real = ClaudeRunError(
        "x", result={"subtype": "success", "is_error": True, "api_error_status": 429, "num_turns": 7, "result": ""},
        rate_limit={"status": "rejected", "resetsAt": reset, "rateLimitType": "five_hour", "isUsingOverage": False},
        limit_message="You've hit your session limit · resets 3:45pm",
    )
    assert usage_limit_reset(real, now=NOW) == NOW + timedelta(hours=1, seconds=60)
    # Message seul (pas d'événement) : limite reconnue, reset par défaut.
    only_message = ClaudeRunError("x", result={"is_error": True, "num_turns": 3, "result": ""},
                                  limit_message="You're out of extra usage · resets 6:40pm")
    assert usage_limit_reset(only_message, now=NOW) is not None
    for text in ("You've hit your weekly limit · resets Mon 12:00am", "You've hit your Opus limit"):
        assert usage_limit_reset(_limit_error(text), now=NOW) is not None
    # resetsAt en millisecondes (certains SDK) : ramené en secondes.
    in_ms = _limit_error(status="rejected", resets_at=reset * 1000)
    assert usage_limit_reset(in_ms, now=NOW) == NOW + timedelta(hours=1, seconds=60)


def test_transient_throttle_message_is_not_a_usage_limit() -> None:
    """Un ralentissement serveur (message `error: "rate_limit"`) puis un échec d'une autre nature : pas de pause."""
    exc = ClaudeRunError("x", result={"subtype": "error_max_turns", "is_error": True, "num_turns": 400, "result": ""},
                         limit_message="Server is temporarily limiting requests")
    assert usage_limit_reset(exc, now=NOW) is None


def test_stream_parser_keeps_synthetic_limit_message() -> None:
    parser = StreamParser()
    parser.feed(json.dumps({
        "type": "assistant", "error": "rate_limit", "isApiErrorMessage": True,
        "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "You've hit your session limit"}]},
    }))
    assert parser.limit_message == "You've hit your session limit"
