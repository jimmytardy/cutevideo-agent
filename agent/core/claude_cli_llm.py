"""Appel LLM texte via Claude Code CLI (`claude -p`) : abonnement Claude, sans clé API.

Alternative à Gemini / à la clé Anthropic pour les agents Python restants. Une seule
réponse, aucun outil, lancé hors du repo pour ne charger ni CLAUDE.md ni hooks.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile

from agent.core.env import env_float
from agent.core.llm_usage import LlmUsageRecord, estimate_llm_cost_usd, record_llm_usage


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


def build_cli_env() -> dict[str, str]:
    env = dict(os.environ)
    # Même règle que Claude Studio : abonnement par défaut, l'API seulement si demandé.
    if os.getenv("CLAUDE_STUDIO_AUTH", "subscription") != "api_key":
        env.pop("ANTHROPIC_API_KEY", None)
    return env


async def call_claude_cli(
    *,
    model: str,
    prompt: str,
    system: str | None = None,
    cacheable_context: str | None = None,
    agent_name: str = "",
) -> str:
    from agent.core.subprocess_registry import register, terminate_proc, unregister

    if not claude_cli_available():
        raise ClaudeCliError(f"CLI Claude introuvable : {claude_cli_bin()} (npm i -g @anthropic-ai/claude-code)")
    full_prompt = "\n\n".join(p.strip() for p in (cacheable_context, prompt) if p and p.strip())
    timeout_s = env_float("CLAUDE_CLI_LLM_TIMEOUT_S", 600.0)

    with tempfile.TemporaryDirectory(prefix="claude-llm-") as cwd:
        proc = await asyncio.create_subprocess_exec(
            *build_cli_command(model, system),
            cwd=cwd,
            env=build_cli_env(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        register(proc)
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(full_prompt.encode("utf-8")), timeout=timeout_s
            )
        except TimeoutError as exc:
            await terminate_proc(proc)
            raise ClaudeCliError(f"{agent_name}: claude -p a dépassé {timeout_s:.0f} s") from exc
        finally:
            unregister(proc)

    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        detail = stderr.decode("utf-8", errors="replace")[-500:] or stdout.decode("utf-8", errors="replace")[-500:]
        raise ClaudeCliError(f"{agent_name}: sortie claude -p illisible (code {proc.returncode}) : {detail}") from exc
    if payload.get("is_error") or proc.returncode != 0:
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
