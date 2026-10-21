from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent.core import studio_resume
from studio.contracts import Brief
from studio.launcher import (
    ALLOWED_TOOLS,
    DISALLOWED_TOOLS,
    REPO_ROOT,
    STALL_TIMEOUT_DEFAULT_S,
    ClaudeRunError,
    LaunchConfig,
    StreamParser,
    _stall_timeout,
    background_tasks_stopped,
    build_command,
    build_env,
    prepare_run_dir,
    run_claude,
)


def _line(payload: dict) -> str:
    return json.dumps(payload) + "\n"


def _assistant(blocks: list, parent: str | None = None) -> str:
    return _line({"type": "assistant", "message": {"content": blocks}, "parent_tool_use_id": parent})


def test_stream_parser_tracks_subagents_and_tools() -> None:
    parser = StreamParser()
    events = parser.feed(_assistant([{
        "type": "tool_use", "id": "t1", "name": "Task",
        "input": {"subagent_type": "monteur", "description": "Montage it. 1", "prompt": "…"},
    }]))
    assert events == [("agent_start", {
        "id": "t1", "role": "monteur", "description": "Montage it. 1", "prompt": "…",
    })]

    events = parser.feed(_assistant(
        [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "python -m studio.tools render"}}],
        parent="t1",
    ))
    assert events[0][0] == "tool"
    assert events[0][1]["role"] == "monteur"

    events = parser.feed(_line({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "ok"}]}]},
    }))
    assert events == [("agent_end", {"id": "t1", "role": "monteur", "is_error": False, "output": "ok"})]


def test_stream_parser_closes_a_background_agent_on_its_real_completion() -> None:
    """Un sous-agent lancé en tâche de fond rend un `tool_result` immédiat qui n'est qu'un accusé.

    Clore l'étape dessus donnait des `AgentRun` de durée nulle portant « Async agent launched… » comme
    rapport — et, plus grave, gonflait le compteur de progrès dont dépend le plafond `STUDIO_MAX_RESUMES`.
    Formes et ordre repris d'un run réel : `task_started` précède l'accusé, `task_notification` suit.
    """
    parser = StreamParser()
    assert parser.feed(_assistant([{
        "type": "tool_use", "id": "t1", "name": "Task",
        "input": {"subagent_type": "monteur", "description": "Montage itération 1", "prompt": "…"},
    }]))[0][0] == "agent_start"

    parser.feed(_line({"type": "system", "subtype": "task_started", "task_id": "bg1",
                       "tool_use_id": "t1", "subagent_type": "monteur", "description": "Montage itération 1"}))
    # L'accusé de lancement ne doit rien clore.
    assert parser.feed(_line({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                 "content": [{"type": "text", "text": "Async agent launched successfully."}]}]},
    })) == []

    done = parser.feed(_line({"type": "system", "subtype": "task_notification", "task_id": "bg1",
                              "tool_use_id": "t1", "status": "completed",
                              "summary": "J'ai écrit timeline.json et rendu renders/v1.mp4"}))
    assert done == [("agent_end", {"id": "t1", "role": "monteur", "is_error": False,
                                   "output": "J'ai écrit timeline.json et rendu renders/v1.mp4"})]


def _start_background(parser: StreamParser, tool_id: str, role: str) -> None:
    """Lance un sous-agent en tâche de fond et consomme son accusé, comme le fait le vrai CLI."""
    parser.feed(_assistant([{"type": "tool_use", "id": tool_id, "name": "Task",
                             "input": {"subagent_type": role, "description": role, "prompt": "…"}}]))
    parser.feed(_line({"type": "system", "subtype": "task_started", "task_id": f"bg_{tool_id}",
                       "tool_use_id": tool_id, "subagent_type": role, "description": role}))
    assert parser.feed(_line({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id,
                                 "content": [{"type": "text", "text": "Async agent launched successfully."}]}]},
    })) == []


def test_stream_parser_reports_a_background_agent_error_from_its_tool_result() -> None:
    """L'échec d'un sous-agent de fond n'arrive que par son `tool_result` : le filtrer rendrait muet.

    C'est le seul porteur du message d'erreur, donc de la détection d'une limite d'usage
    (`_ProgressRecorder.limit_failures`) ; sans lui l'étape resterait ouverte jusqu'à `close_dangling()`,
    qui la clôrait sur un motif générique en perdant la vraie cause.
    """
    parser = StreamParser()
    _start_background(parser, "t1", "monteur")
    assert parser.feed(_line({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                                 "content": [{"type": "text", "text": "Claude AI usage limit reached"}]}]},
    })) == [("agent_end", {"id": "t1", "role": "monteur", "is_error": True,
                           "output": "Claude AI usage limit reached"})]


def test_stream_parser_leaves_a_task_stopped_mid_work_open() -> None:
    """Une tâche tuée est notifiée `stopped` : l'étape doit rester ouverte pour `close_dangling()`.

    La clore en succès referait du travail perdu un « progrès », ce qui désarmait `STUDIO_MAX_RESUMES` ;
    la clore en échec priverait la reprise de son statut `interrupted`.
    """
    parser = StreamParser()
    _start_background(parser, "t1", "monteur")
    assert parser.feed(_line({"type": "system", "subtype": "task_notification", "task_id": "bg_t1",
                              "tool_use_id": "t1", "status": "stopped", "summary": "Tâche de fond"})) == []
    # Une notification reçue prouve que le mécanisme fonctionne : pas de repli sur l'accusé.
    assert parser.feed(_line({"type": "result", "subtype": "success"})) == [
        ("result", {"type": "result", "subtype": "success"})
    ]


def test_stream_parser_falls_back_to_the_ack_when_the_cli_notifies_nothing() -> None:
    """Si le CLI cessait de notifier ses tâches, les accusés reprennent du service en fin de session.

    Image inversée du bug corrigé : sans ce repli, toutes les étapes d'une création réussie seraient
    closes en échec par `close_dangling()`, et le compteur de progrès resté à zéro ferait abandonner au
    plafond `STUDIO_MAX_RESUMES` une création qui avance.
    """
    parser = StreamParser()
    _start_background(parser, "t1", "monteur")
    assert parser.feed(_line({"type": "result", "subtype": "success"})) == [
        ("agent_end", {"id": "t1", "role": "monteur", "is_error": False,
                       "output": "Async agent launched successfully."}),
        ("result", {"type": "result", "subtype": "success"}),
    ]


def test_stream_parser_still_closes_a_foreground_agent_on_its_tool_result() -> None:
    """Sans `task_started`, le `tool_result` porte bien le rapport : il doit continuer à clore l'étape."""
    parser = StreamParser()
    parser.feed(_assistant([{"type": "tool_use", "id": "t9", "name": "Task",
                             "input": {"subagent_type": "voix", "description": "Voix", "prompt": "…"}}]))
    events = parser.feed(_line({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t9",
                                 "content": [{"type": "text", "text": "voice.wav écrit"}]}]},
    }))
    assert events == [("agent_end", {"id": "t9", "role": "voix", "is_error": False, "output": "voice.wav écrit"})]


def test_stream_parser_tolerates_odd_messages() -> None:
    parser = StreamParser()
    assert parser.feed("not json") == []
    assert parser.feed(_line({"type": "system", "subtype": "notice", "message": "texte"})) == []
    denied = parser.feed(_line({"type": "system", "subtype": "permission_denied", "tool_name": "Bash", "message": "x"}))
    assert denied == [("denied", {"role": "producteur", "name": "Bash"})]
    assert parser.feed(_line({"type": "assistant", "message": {"content": ["brut", {"type": "text"}]}})) == []
    result = parser.feed(_line({"type": "result", "subtype": "success", "is_error": False}))
    assert result[0][0] == "result"
    assert parser.result is not None


def test_stream_parser_reports_killed_background_tasks() -> None:
    """Claude Code tue ses tâches de fond au plafond d'attente puis sort « avec succès » : seul
    `task_updated`/`killed` fait foi, les autres événements ne servent qu'à nommer la tâche."""
    parser = StreamParser()
    assert parser.feed(_line({
        "type": "system", "subtype": "background_tasks_changed",
        "tasks": [{"task_id": "bg1", "task_type": "local_agent", "subagent_type": "monteur",
                   "description": "Montage itération 1"}],
    })) == []
    assert parser.killed_task_ids == set()

    killed = parser.feed(_line({
        "type": "system", "subtype": "task_updated", "task_id": "bg1", "patch": {"status": "killed"},
    }))
    assert killed == [("task_killed", {"id": "bg1", "label": "Montage itération 1"})]
    assert parser.killed_task_ids == {"bg1"}

    # `task_started` nomme aussi une tâche (`background_tasks_changed` peut être coalescé par le CLI).
    # Forme réelle du CLI, vérifiée dans son bundle : le libellé est à la racine, pas sous une clé `task`.
    parser.feed(_line({"type": "system", "subtype": "task_started", "task_id": "bg3",
                       "description": "", "subagent_type": "voix"}))
    assert parser.feed(_line({
        "type": "system", "subtype": "task_updated", "task_id": "bg3", "patch": {"status": "killed"},
    })) == [("task_killed", {"id": "bg3", "label": "voix"})]

    # Une tâche qui se termine normalement n'est pas signalée.
    assert parser.feed(_line({
        "type": "system", "subtype": "task_updated", "task_id": "bg2", "patch": {"status": "completed"},
    })) == []
    assert "bg2" not in parser.killed_task_ids


def test_stream_parser_names_killed_task_from_later_notification() -> None:
    """Le libellé arrive parfois après la mise à mort (`task_notification`) : il doit l'enrichir."""
    parser = StreamParser()
    parser.feed(_line({"type": "system", "subtype": "task_updated", "task_id": "bg1", "patch": {"status": "killed"}}))
    assert parser.killed_task_ids == {"bg1"}
    events = parser.feed(_line({
        "type": "system", "subtype": "task_notification", "task_id": "bg1", "status": "stopped",
        "summary": "python -m studio.tools animate-template --template paradox",
    }))
    assert events == [("task_killed", {
        "id": "bg1", "label": "python -m studio.tools animate-template --template paradox",
    })]


def test_build_env_removes_the_cli_wait_ceiling_on_background_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un rôle prend le temps qu'il faut : sans cela, le montage est tué à 10 min en plein travail.

    `0` est ce que le CLI lit comme « attendre indéfiniment » ; c'est le watchdog d'inactivité qui
    rattrape un blocage réel (`--max-turns` compte des tours, pas du temps). Reste surchargeable.
    """
    assert build_env(tmp_path)["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "0"
    monkeypatch.setenv("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "900000")
    assert build_env(tmp_path)["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "900000"


def test_background_tasks_stopped_reads_the_cli_announcement(tmp_path: Path) -> None:
    """Discriminant d'une session coupée en plein travail : seul ce message du CLI la caractérise."""
    assert not background_tasks_stopped(tmp_path)  # pas de stderr du tout
    (tmp_path / "claude_stderr.log").write_text("rien d'anormal\n", encoding="utf-8")
    assert not background_tasks_stopped(tmp_path)
    (tmp_path / "claude_stderr.log").write_text(
        'Background tasks still running 10m after the last turn (subagent "monteur"); stopping them.\n',
        encoding="utf-8",
    )
    assert background_tasks_stopped(tmp_path)


class _FakeStdout:
    """`StreamReader` minimal : rend les lignes une à une après `delay`, puis se tait ou se ferme."""

    def __init__(self, lines: list[str], delay: float, never_ends: bool) -> None:
        self._lines = list(lines)
        self._delay = delay
        self._never_ends = never_ends

    async def readline(self) -> bytes:
        await asyncio.sleep(self._delay)
        if self._lines:
            return self._lines.pop(0).encode("utf-8")
        if self._never_ends:
            await asyncio.sleep(3600)  # silence : c'est au watchdog de trancher
        return b""


class _FakeProc:
    def __init__(self, lines: list[str], *, delay: float = 0.0, never_ends: bool = False) -> None:
        self.stdout = _FakeStdout(lines, delay, never_ends)
        self.returncode: int | None = None
        self.pid = 4242

    async def wait(self) -> int:
        self.returncode = 0
        return 0


def _fake_cli(monkeypatch: pytest.MonkeyPatch, proc: _FakeProc) -> list[_FakeProc]:
    """Branche `run_claude` sur `proc` et renvoie la liste des process effectivement tués.

    Le patch vise `agent.core.subprocess_registry.terminate_proc` parce que `run_claude` l'importe à
    l'intérieur de la fonction : remonter cet import en tête de module casserait ce test en silence.
    """
    terminated: list[_FakeProc] = []

    async def _terminate(target, **_kwargs) -> None:
        terminated.append(target)

    async def _spawn(*_args, **_kwargs) -> _FakeProc:
        return proc

    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/claude")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setattr("agent.core.subprocess_registry.terminate_proc", _terminate)
    return terminated


def _result_line(turns: int = 3) -> str:
    return _line({"type": "result", "subtype": "success", "is_error": False, "num_turns": turns})


@pytest.mark.asyncio
async def test_pump_raises_on_prolonged_silence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Un flux muet doit couper la session : sinon une création bloquée garde le créneau de sa chaîne."""
    monkeypatch.setenv("STUDIO_STALL_TIMEOUT_S", "0.05")
    proc = _FakeProc([], never_ends=True)
    terminated = _fake_cli(monkeypatch, proc)

    with pytest.raises(ClaudeRunError) as excinfo:
        await run_claude(tmp_path, cfg=LaunchConfig(claude_bin="claude"))

    assert excinfo.value.stalled
    assert "sans activité" in str(excinfo.value)
    assert terminated == [proc]  # tout le groupe de processus est tué


@pytest.mark.asyncio
async def test_stall_error_carries_the_usage_limit_seen_before_the_silence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sans cette propagation, une limite atteinte juste avant le silence donnerait une reprise immédiate
    au lieu d'une pause jusqu'au reset — et chaque reprise la heurterait à nouveau."""
    monkeypatch.setenv("STUDIO_STALL_TIMEOUT_S", "0.05")
    rate_limit = {"status": "rejected", "resetsAt": 1792600000, "rateLimitType": "five_hour"}
    proc = _FakeProc([_line({"type": "rate_limit_event", "rate_limit_info": rate_limit})], never_ends=True)
    _fake_cli(monkeypatch, proc)

    with pytest.raises(ClaudeRunError) as excinfo:
        await run_claude(tmp_path, cfg=LaunchConfig(claude_bin="claude"))

    assert excinfo.value.stalled
    assert excinfo.value.rate_limit == rate_limit
    # Ce qui compte en aval : la limite redevient reconnaissable, donc le runner mettra en pause.
    assert studio_resume.usage_limit_reset(excinfo.value) is not None


@pytest.mark.asyncio
async def test_pump_silence_counter_is_rearmed_by_each_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Le seuil mesure le silence entre deux lignes, pas la durée totale : un flux lent mais vivant passe."""
    monkeypatch.setenv("STUDIO_STALL_TIMEOUT_S", "0.3")
    # 6 lignes espacées de 0,1 s : 0,6 s au total, soit bien plus que le seuil, mais jamais 0,3 s de
    # silence d'affilée.
    proc = _FakeProc([_result_line()] * 6, delay=0.1)
    _fake_cli(monkeypatch, proc)

    assert (await run_claude(tmp_path, cfg=LaunchConfig(claude_bin="claude")))["num_turns"] == 3


@pytest.mark.asyncio
async def test_pump_without_stall_timeout_waits_indefinitely(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`STUDIO_STALL_TIMEOUT_S=0` désactive la surveillance, comme `CLAUDE_STUDIO_TIMEOUT_S=0`.

    Le contraste avec le défaut est vérifié d'abord : variable absente → seuil actif, `0` → désarmé. Sans
    ce premier assert, le test passerait aussi pour un défaut qui se trouverait être inoffensif.
    """
    monkeypatch.delenv("STUDIO_STALL_TIMEOUT_S", raising=False)
    assert _stall_timeout() == STALL_TIMEOUT_DEFAULT_S
    monkeypatch.setenv("STUDIO_STALL_TIMEOUT_S", "0")
    assert _stall_timeout() is None
    proc = _FakeProc([_result_line(turns=1)], delay=0.15)
    _fake_cli(monkeypatch, proc)

    assert (await run_claude(tmp_path, cfg=LaunchConfig(claude_bin="claude")))["num_turns"] == 1


@pytest.mark.asyncio
async def test_session_timeout_is_not_reported_as_a_stall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Les deux délais ne doivent pas être confondus : le délai global n'est pas une inactivité reprenable."""
    monkeypatch.setenv("STUDIO_STALL_TIMEOUT_S", "0")  # seule la limite de session peut se déclencher
    proc = _FakeProc([], never_ends=True)
    terminated = _fake_cli(monkeypatch, proc)

    with pytest.raises(ClaudeRunError) as excinfo:
        await run_claude(tmp_path, cfg=LaunchConfig(claude_bin="claude", timeout_s=0.05))

    assert not excinfo.value.stalled  # sinon la création serait reprise au lieu d'échouer
    assert "interrompue après" in str(excinfo.value)
    assert terminated == [proc]


def test_build_command_keeps_prompt_before_variadic_flags() -> None:
    cmd = build_command(LaunchConfig(model="claude-opus-5-5", claude_bin="claude"))
    assert cmd[:3] == ["claude", "-p", "/make-video"]
    assert "Bash(python -m studio.tools:*)" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    # Les options variadiques ne doivent pas avaler une option suivante.
    allowed_end = cmd.index("--allowedTools") + 1 + len(ALLOWED_TOOLS)
    assert cmd[allowed_end].startswith("--")
    # Recherche web autorisée (le scénariste vérifie ses faits ; restreinte par le frontmatter des rôles).
    assert {"WebSearch", "WebFetch"} <= set(cmd[cmd.index("--allowedTools") + 1:allowed_end])
    # Refus explicites : sans outil de mise à mort, l'agent ne peut pas faire déclarer une de ses tâches
    # `killed` et forger ainsi le signal de reprise (cf. `background_tasks_stopped`).
    denied_start = cmd.index("--disallowedTools") + 1
    denied_end = denied_start + len(DISALLOWED_TOOLS)
    assert cmd[denied_start:denied_end] == list(DISALLOWED_TOOLS)
    assert cmd[denied_end].startswith("--")  # l'option variadique n'avale pas la suivante


def test_build_env_strips_inherited_secrets_and_injects_user_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agent.core.api_keys import UserKeys
    from studio.user_keys import INHERITED_SECRET_VARS

    for name in INHERITED_SECRET_VARS:
        monkeypatch.setenv(name, "platform-secret")
    env = build_env(tmp_path)
    assert not set(INHERITED_SECRET_VARS) & set(env)
    assert env["STUDIO_RUN_DIR"] == str(tmp_path)
    assert str(REPO_ROOT) in env["PYTHONPATH"]

    assert "STUDIO_GCP_LOCATION" in INHERITED_SECRET_VARS

    keys = UserKeys(
        anthropic="sk-ant-api-user", gemini="g-user", azure_speech="az", azure_speech_region="westeurope",
        gcp_credentials_json='{"project_id": "p"}', gcp_location="us-central1",
    )
    env = build_env(tmp_path, keys, config_dir=tmp_path / "cfg")
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-api-user"
    assert env["STUDIO_GEMINI_API_KEY"] == "g-user"
    assert env["STUDIO_AZURE_SPEECH_KEY"] == "az"
    assert env["STUDIO_AZURE_SPEECH_REGION"] == "westeurope"
    assert env["STUDIO_GCP_CREDENTIALS_JSON"] == '{"project_id": "p"}'
    assert env["STUDIO_GCP_LOCATION"] == "us-central1"
    assert "STUDIO_FAL_KEY" not in env and "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "cfg") and (tmp_path / "cfg").is_dir()


@pytest.mark.parametrize(("brief_cap", "platform_cap", "expected"), [(0, "4", "0"), (2, "4", "2"), (10, "4", "4")])
def test_build_env_caps_ai_images_from_brief(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, brief_cap: int, platform_cap: str, expected: str
) -> None:
    monkeypatch.setenv("STUDIO_MAX_AI_IMAGES", platform_cap)
    (tmp_path / "brief.json").write_text(
        json.dumps({"theme": "t", "max_ai_images": brief_cap}), encoding="utf-8"
    )
    assert build_env(tmp_path)["STUDIO_MAX_AI_IMAGES"] == expected


def test_prepare_run_dir_copies_workspace(tmp_path: Path) -> None:
    run_dir = prepare_run_dir(tmp_path / "run", Brief(theme="Les volcans", target_duration_s=30))
    assert (run_dir / "CLAUDE.md").exists()
    assert (run_dir / ".claude" / "commands" / "make-video.md").exists()
    for role in ("scenariste", "voix", "monteur", "miniaturiste", "critique"):
        assert (run_dir / ".claude" / "agents" / f"{role}.md").exists()
    brief = json.loads((run_dir / "brief.json").read_text(encoding="utf-8"))
    assert brief["theme"] == "Les volcans"
    assert brief["target_duration_s"] == 30


def test_prepare_run_dir_refuses_repo_paths() -> None:
    with pytest.raises(ValueError, match="hors du repo"):
        prepare_run_dir(REPO_ROOT / "tmp" / "studio-run", Brief(theme="x"))


def test_session_timeout_zero_means_unlimited(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_STUDIO_TIMEOUT_S", "0")
    assert LaunchConfig().timeout_s is None
    monkeypatch.setenv("CLAUDE_STUDIO_TIMEOUT_S", "7200")
    assert LaunchConfig().timeout_s == 7200.0
    # Sans limite par défaut : un plafond absolu couperait un montage animé en `failed` non reprenable,
    # et s'il tombait sous le seuil d'inactivité il se déclencherait toujours le premier, rendant le
    # watchdog inatteignable.
    monkeypatch.delenv("CLAUDE_STUDIO_TIMEOUT_S")
    assert LaunchConfig().timeout_s is None
    assert STALL_TIMEOUT_DEFAULT_S > 0  # le relais du plafond retiré
