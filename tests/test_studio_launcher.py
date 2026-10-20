from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.contracts import Brief
from studio.launcher import (
    ALLOWED_TOOLS,
    BG_WAIT_CEILING_MS,
    REPO_ROOT,
    LaunchConfig,
    StreamParser,
    background_tasks_stopped,
    build_command,
    build_env,
    prepare_run_dir,
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
    assert parser.killed_tasks == {}

    killed = parser.feed(_line({
        "type": "system", "subtype": "task_updated", "task_id": "bg1", "patch": {"status": "killed"},
    }))
    assert killed == [("task_killed", {"id": "bg1", "label": "Montage itération 1"})]
    assert parser.killed_tasks == {"bg1": "Montage itération 1"}

    # `task_started` nomme aussi une tâche (`background_tasks_changed` peut être coalescé par le CLI).
    parser.feed(_line({"type": "system", "subtype": "task_started",
                       "task": {"task_id": "bg3", "subagent_type": "voix"}}))
    assert parser.feed(_line({
        "type": "system", "subtype": "task_updated", "task_id": "bg3", "patch": {"status": "killed"},
    })) == [("task_killed", {"id": "bg3", "label": "voix"})]

    # Une tâche qui se termine normalement n'est pas signalée.
    assert parser.feed(_line({
        "type": "system", "subtype": "task_updated", "task_id": "bg2", "patch": {"status": "completed"},
    })) == []
    assert "bg2" not in parser.killed_tasks


def test_stream_parser_names_killed_task_from_later_notification() -> None:
    """Le libellé arrive parfois après la mise à mort (`task_notification`) : il doit l'enrichir."""
    parser = StreamParser()
    parser.feed(_line({"type": "system", "subtype": "task_updated", "task_id": "bg1", "patch": {"status": "killed"}}))
    assert parser.killed_tasks == {"bg1": ""}
    events = parser.feed(_line({
        "type": "system", "subtype": "task_notification", "task_id": "bg1", "status": "stopped",
        "summary": "python -m studio.tools animate-template --template paradox",
    }))
    assert events == [("task_killed", {
        "id": "bg1", "label": "python -m studio.tools animate-template --template paradox",
    })]


def test_build_env_removes_the_cli_wait_ceiling_on_background_tasks(tmp_path: Path) -> None:
    """Un rôle prend le temps qu'il faut : sans cela, le montage est tué à 10 min en plein travail.

    `0` = sans limite côté CLI ; les blocages restent bornés par les délais des outils (sandbox, ffmpeg,
    `BASH_MAX_TIMEOUT_MS`) et par `--max-turns`.
    """
    assert BG_WAIT_CEILING_MS == 0
    assert build_env(tmp_path)["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "0"


def test_build_env_background_ceiling_stays_overridable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    assert "--disallowedTools" not in cmd


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
    monkeypatch.delenv("CLAUDE_STUDIO_TIMEOUT_S")
    assert LaunchConfig().timeout_s == 3600.0
