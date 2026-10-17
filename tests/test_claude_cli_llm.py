"""Fournisseur LLM « Claude CLI » : abonnement Claude d'un admin (token `claude setup-token`)."""

from __future__ import annotations

import asyncio
import json
import stat
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core import api_key_validation, claude_cli_llm
from agent.core.agent_llm_constraints import CLAUDE_CLI_MODELS, normalize_preference
from agent.core.api_keys import ApiKeyContext, UserKeys, resolve_api_key
from agent.core.llm_resolver import call_llm, parse_agent_preferences
from studio.user_keys import studio_env

TOKEN = "sk-ant-oat01-admin-token"


def _fake_cli(tmp_path: Path, *, result: str, is_error: bool = False) -> Path:
    """Faux `claude` : enregistre argv/stdin/env et renvoie un JSON `-p --output-format json`."""
    log = tmp_path / "calls.json"
    script = tmp_path / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd(),"
        f" 'token': os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'), 'has_api_key': 'ANTHROPIC_API_KEY' in os.environ,"
        f" 'has_gemini': 'GOOGLE_GEMINI_API_KEY' in os.environ}}, open({str(log)!r}, 'w'))\n"
        f"print(json.dumps({{'type': 'result', 'is_error': {is_error!r}, 'result': {result!r},"
        " 'usage': {'input_tokens': 10, 'output_tokens': 5}}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _user_with_cli_pref() -> MagicMock:
    user = MagicMock(id=uuid.uuid4())
    user.agent_llm_preferences = {
        "content_planner_agent": {"provider": "claude_cli", "model": "claude-opus-5-5", "tier": "free"}
    }
    return user


def _keys(token: str | None):
    async def fake(_session, uid, provider, *, purpose, tier="free"):
        key = token if provider == "claude_subscription" else None
        return ApiKeyContext(user_id=uid, provider=provider, key=key, source="user" if key else "none", tier=tier)

    return fake


def test_preference_is_kept_and_normalized() -> None:
    prefs = parse_agent_preferences({"content_planner_agent": {"provider": "claude_cli", "model": "x", "tier": "paid"}})
    pref = normalize_preference(prefs["content_planner_agent"])
    assert (pref.provider, pref.model, pref.tier) == ("claude_cli", CLAUDE_CLI_MODELS[0], "free")


def test_call_llm_routes_to_cli_with_the_admin_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_BIN", str(_fake_cli(tmp_path, result='{"ok": true}')))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "should-not-leak")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "platform-token-should-not-leak")

    with patch("agent.core.llm_resolver.resolve_api_key", side_effect=_keys(TOKEN)):
        text = asyncio.run(call_llm(AsyncMock(), _user_with_cli_pref(), "content_planner_agent", "Le sujet ?",
                                    system="Réponds en JSON.", cacheable_context="Contexte chaîne"))
    assert text == '{"ok": true}'
    call = json.loads((tmp_path / "calls.json").read_text())
    assert call["argv"][call["argv"].index("--model") + 1] == "claude-opus-5-5"
    assert call["argv"][call["argv"].index("--system-prompt") + 1] == "Réponds en JSON."
    assert call["stdin"] == "Contexte chaîne\n\nLe sujet ?"
    assert call["token"] == TOKEN
    assert not call["has_api_key"] and not call["has_gemini"]
    assert not Path(call["cwd"]).exists()  # dossier temporaire hors du repo, nettoyé


def test_cli_preference_without_token_falls_back_to_other_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch("agent.core.llm_resolver.resolve_api_key", side_effect=_keys(None)):
        with pytest.raises(RuntimeError, match="Clés API"):
            asyncio.run(call_llm(AsyncMock(), _user_with_cli_pref(), "content_planner_agent", "x"))


def test_cli_error_is_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_BIN", str(_fake_cli(tmp_path, result="quota", is_error=True)))
    with pytest.raises(claude_cli_llm.ClaudeCliError, match="quota"):
        asyncio.run(claude_cli_llm.call_claude_cli(model="claude-sonnet-5-5", prompt="x", oauth_token=TOKEN))


@pytest.mark.asyncio
async def test_subscription_token_is_ignored_for_non_admins() -> None:
    row = MagicMock(encrypted_key=None, metadata_=None)
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=False)  # User.is_admin
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=row)))
    ctx = await resolve_api_key(session, uuid.uuid4(), "claude_subscription", purpose="studio")
    assert (ctx.source, ctx.key) == ("none", None)
    session.execute.assert_not_awaited()


def test_studio_prefers_subscription_over_api_key() -> None:
    env = studio_env(UserKeys(anthropic="sk-ant-api-x", claude_subscription=TOKEN))
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN and "ANTHROPIC_API_KEY" not in env
    env = studio_env(UserKeys(anthropic="sk-ant-api-x"))
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-api-x" and "CLAUDE_CODE_OAUTH_TOKEN" not in env


@pytest.mark.asyncio
async def test_subscription_health_from_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_BIN", str(_fake_cli(tmp_path, result="ok")))
    assert (await api_key_validation.check_api_key("claude_subscription", TOKEN)).status == "ok"
    assert (await api_key_validation.check_api_key("claude_subscription", "sk-ant-api03-x")).status == "invalid"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("Failed to authenticate. API Error: 401 OAuth access token is invalid.", "invalid"),
        ("OAuth token has expired", "expired"),
        ("Claude AI usage limit reached|1760000000", "quota"),
    ],
)
def test_subscription_errors(error: str, expected: str) -> None:
    assert api_key_validation._classify_claude_subscription(error).status == expected
