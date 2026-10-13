from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.contracts import Brief
from studio.launcher import (
    REPO_ROOT,
    LaunchConfig,
    StreamParser,
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


def test_build_command_keeps_prompt_before_variadic_flags() -> None:
    cmd = build_command(LaunchConfig(model="claude-opus-5-5", claude_bin="claude"))
    assert cmd[:3] == ["claude", "-p", "/make-video"]
    assert "Bash(python -m studio.tools:*)" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    # Les options variadiques ne doivent pas avaler une option suivante.
    after_disallowed = cmd[cmd.index("--disallowedTools") + 1:]
    assert after_disallowed[2].startswith("--")


def test_build_env_prefers_subscription(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("CLAUDE_STUDIO_AUTH", raising=False)
    env = build_env(tmp_path)
    assert "ANTHROPIC_API_KEY" not in env
    assert env["STUDIO_RUN_DIR"] == str(tmp_path)
    assert str(REPO_ROOT) in env["PYTHONPATH"]

    monkeypatch.setenv("CLAUDE_STUDIO_AUTH", "api_key")
    assert build_env(tmp_path)["ANTHROPIC_API_KEY"] == "sk-test"


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
