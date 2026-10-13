"""Fournisseur LLM « Claude CLI » (abonnement Claude, sans clé) pour les agents Python."""

from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path

import pytest

from agent.core import claude_cli_llm
from agent.core.agent_llm_constraints import CLAUDE_CLI_MODELS, normalize_agent_preference
from agent.core.llm_resolver import AgentLlmPreference, call_llm, parse_agent_preferences


def _fake_cli(tmp_path: Path, *, result: str, is_error: bool = False) -> Path:
    """Faux `claude` : enregistre argv/stdin/env et renvoie un JSON `-p --output-format json`."""
    log = tmp_path / "calls.json"
    script = tmp_path / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd(),"
        f" 'has_api_key': 'ANTHROPIC_API_KEY' in os.environ}}, open({str(log)!r}, 'w'))\n"
        f"print(json.dumps({{'type': 'result', 'is_error': {is_error!r}, 'result': {result!r},"
        " 'usage': {'input_tokens': 10, 'output_tokens': 5}}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_preference_is_kept_and_normalized() -> None:
    prefs = parse_agent_preferences({"content_planner_agent": {"provider": "claude_cli", "model": "x", "tier": "paid"}})
    pref = normalize_agent_preference("content_planner_agent", prefs["content_planner_agent"])
    assert (pref.provider, pref.model, pref.tier) == ("claude_cli", CLAUDE_CLI_MODELS[0], "free")


def test_call_llm_routes_to_cli_without_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_BIN", str(_fake_cli(tmp_path, result='{"ok": true}')))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.delenv("CLAUDE_STUDIO_AUTH", raising=False)

    class _User:
        id = None
        agent_llm_preferences = {
            "content_planner_agent": {"provider": "claude_cli", "model": "claude-opus-5-5", "tier": "free"}
        }

    text = asyncio.run(call_llm(None, _User(), "content_planner_agent", "Le sujet ?",  # type: ignore[arg-type]
                                system="Réponds en JSON.", cacheable_context="Contexte chaîne"))
    assert text == '{"ok": true}'
    call = json.loads((tmp_path / "calls.json").read_text())
    assert call["argv"][call["argv"].index("--model") + 1] == "claude-opus-5-5"
    assert call["argv"][call["argv"].index("--tools") + 1] == ""
    assert call["argv"][call["argv"].index("--system-prompt") + 1] == "Réponds en JSON."
    assert call["stdin"] == "Contexte chaîne\n\nLe sujet ?"
    assert not call["has_api_key"]
    assert not Path(call["cwd"]).exists()  # dossier temporaire hors du repo, nettoyé


def test_cli_error_is_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_BIN", str(_fake_cli(tmp_path, result="quota", is_error=True)))
    with pytest.raises(claude_cli_llm.ClaudeCliError, match="quota"):
        asyncio.run(claude_cli_llm.call_claude_cli(model="claude-sonnet-5-5", prompt="x"))
