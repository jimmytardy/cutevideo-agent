"""Appel LLM texte via Claude Code CLI (`claude -p`) avec l'abonnement Claude d'un admin.

Le token d'abonnement (`claude setup-token`, fournisseur `claude_subscription`, réservé aux
admins pour leur propre usage) est passé explicitement : aucun secret hérité n'est transmis.
Une seule réponse, aucun outil, lancé hors du repo pour ne charger ni CLAUDE.md ni hooks.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile

from agent.core.env import env_float
from agent.core.llm_usage import LlmUsageRecord, estimate_llm_cost_usd, record_llm_usage
from studio.user_keys import INHERITED_SECRET_VARS


class ClaudeCliError(RuntimeError):
    pass


def claude_cli_bin() -> str:
    return os.getenv("CLAUDE_BIN", "claude")


def claude_cli_available() -> bool:
    return shutil.which(claude_cli_bin()) is not None


def build_cli_command(model: str, system: str | None) -> list[str]:
    cmd = [
        claude_cli_bin(), "-p",
        "--output-format", "json",
        "--model", model,
        "--tools", "",
        "--setting-sources", "",
        "--no-session-persistence",
    ]
    if system and system.strip():
        cmd += ["--system-prompt", system.strip()]
    return cmd


def build_cli_env(oauth_token: str) -> dict[str, str]:
    """Environnement du CLI : aucune clé héritée, seulement le token d'abonnement de l'utilisateur."""
    env = {name: value for name, value in os.environ.items() if name not in INHERITED_SECRET_VARS}
    env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    return env


async def _run_cli(cmd: list[str], env: dict[str, str], stdin: str, timeout_s: float) -> tuple[dict, int, str]:
    """Lance `claude -p` dans un dossier vide ; renvoie (payload JSON, code retour, stderr)."""
    from agent.core.subprocess_registry import register, terminate_proc, unregister

    if not claude_cli_available():
        raise ClaudeCliError(f"CLI Claude introuvable : {claude_cli_bin()} (npm i -g @anthropic-ai/claude-code)")
    with tempfile.TemporaryDirectory(prefix="claude-llm-") as cwd:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        register(proc)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin.encode("utf-8")), timeout=timeout_s)
        except TimeoutError as exc:
            await terminate_proc(proc)
            raise ClaudeCliError(f"claude -p a dépassé {timeout_s:.0f} s") from exc
        finally:
            unregister(proc)
    err = stderr.decode("utf-8", errors="replace")
    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        detail = err[-500:] or stdout.decode("utf-8", errors="replace")[-500:]
        raise ClaudeCliError(f"sortie claude -p illisible (code {proc.returncode}) : {detail}") from exc
    return payload, proc.returncode or 0, err


async def call_claude_cli(
    *,
    model: str,
    prompt: str,
    oauth_token: str,
    system: str | None = None,
    cacheable_context: str | None = None,
    agent_name: str = "",
) -> str:
    full_prompt = "\n\n".join(p.strip() for p in (cacheable_context, prompt) if p and p.strip())
    timeout_s = env_float("CLAUDE_CLI_LLM_TIMEOUT_S", 600.0)
    try:
        payload, code, _ = await _run_cli(
            build_cli_command(model, system), build_cli_env(oauth_token), full_prompt, timeout_s
        )
    except ClaudeCliError as exc:
        raise ClaudeCliError(f"{agent_name}: {exc}") from exc
    if payload.get("is_error") or code != 0:
        raise ClaudeCliError(f"{agent_name}: claude -p en erreur : {str(payload.get('result'))[:500]}")

    usage = payload.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) \
        + int(usage.get("cache_creation_input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    record_llm_usage(LlmUsageRecord(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=estimate_llm_cost_usd(model, input_tokens, output_tokens),
    ))
    return str(payload.get("result") or "")


async def probe_subscription_token(oauth_token: str) -> tuple[bool, str]:
    """Une réponse minimale du CLI avec ce token : (succès, message d'erreur du CLI)."""
    payload, code, err = await _run_cli(
        [*build_cli_command("claude-haiku-5-5", None), "--max-turns", "1"],
        build_cli_env(oauth_token),
        "Réponds juste : ok",
        timeout_s=120.0,
    )
    if payload.get("is_error") or code != 0:
        return False, str(payload.get("result") or err)[:300]
    return True, ""
