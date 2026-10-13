"""Lancement de Claude Code en headless (`claude -p /make-video`) sur un run dir.

Partagé par le CLI local (`studio.run`) et le runner du pipeline
(`agent.core.claude_studio`). Le run dir reçoit une copie de
`studio/workspace/` (CLAUDE.md + .claude/ : commande, sous-agents, permissions)
et un `brief.json`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from studio.contracts import Brief

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_TEMPLATE = Path(__file__).resolve().parent / "workspace"
ROLES = ("scenariste", "voix", "monteur", "miniaturiste", "critique")
SUBAGENT_TOOLS = ("Agent", "Task")
# Passées en ligne de commande : les permissions d'un .claude/settings.json sont
# ignorées tant que le dossier n'a pas été marqué « de confiance » interactivement.
ALLOWED_TOOLS = ("Bash(python -m studio.tools:*)", "Read", "Write", "Edit", "Glob", *SUBAGENT_TOOLS)
DISALLOWED_TOOLS = ("WebFetch", "WebSearch")
# Ligne stream-json max (les tool_result peuvent contenir de gros JSON).
_STREAM_LIMIT = 16 * 1024 * 1024

EventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


def default_runs_dir() -> Path:
    """Hors du repo : sinon Claude chargerait aussi le CLAUDE.md de développement."""
    configured = os.getenv("STUDIO_RUNS_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".cache" / "cutevideo" / "runs"


def prepare_run_dir(run_dir: Path, brief: Brief) -> Path:
    run_dir = run_dir.resolve()
    if run_dir.is_relative_to(REPO_ROOT):
        raise ValueError(f"le run dir doit être hors du repo ({REPO_ROOT}) : {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WORKSPACE_TEMPLATE / "CLAUDE.md", run_dir / "CLAUDE.md")
    shutil.copytree(WORKSPACE_TEMPLATE / ".claude", run_dir / ".claude", dirs_exist_ok=True)
    shutil.copytree(WORKSPACE_TEMPLATE / "anim", run_dir / "anim", dirs_exist_ok=True)
    (run_dir / "brief.json").write_text(
        brief.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
    )
    return run_dir


@dataclass
class LaunchConfig:
    model: str = field(default_factory=lambda: os.getenv("CLAUDE_STUDIO_MODEL", "claude-opus-5-5"))
    timeout_s: float = field(default_factory=lambda: float(os.getenv("CLAUDE_STUDIO_TIMEOUT_S", "3600")))
    max_turns: int = field(default_factory=lambda: int(os.getenv("CLAUDE_STUDIO_MAX_TURNS", "400")))
    max_budget_usd: float | None = field(
        default_factory=lambda: float(os.environ["CLAUDE_STUDIO_MAX_BUDGET_USD"])
        if os.getenv("CLAUDE_STUDIO_MAX_BUDGET_USD")
        else None
    )
    claude_bin: str = field(default_factory=lambda: os.getenv("CLAUDE_BIN", "claude"))


def permission_args() -> list[str]:
    return ["--allowedTools", *ALLOWED_TOOLS, "--disallowedTools", *DISALLOWED_TOOLS]


def build_command(cfg: LaunchConfig, prompt: str = "/make-video") -> list[str]:
    cmd = [
        cfg.claude_bin, "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--model", cfg.model,
        "--max-turns", str(cfg.max_turns),
        *permission_args(),
        "--permission-mode", "dontAsk",
        # Ni hooks ni plugins utilisateur : seuls les réglages du run dir.
        "--setting-sources", "project",
        "--no-session-persistence",
    ]
    if cfg.max_budget_usd:
        cmd += ["--max-budget-usd", str(cfg.max_budget_usd)]
    return cmd


def _brief_animations(run_dir: Path) -> str:
    try:
        return Brief.model_validate_json((run_dir / "brief.json").read_text(encoding="utf-8")).animations
    except (OSError, ValueError):
        return "off"


def build_env(run_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    python_bin = str(Path(sys.executable).parent)
    env["PATH"] = f"{python_bin}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH")]))
    env["STUDIO_RUN_DIR"] = str(run_dir)
    # Niveau d'animation lu ici, avant que Claude ne puisse toucher brief.json : les outils
    # `animate*` ne font confiance qu'à cette variable.
    env["STUDIO_ANIMATIONS"] = _brief_animations(run_dir)
    # Rendus et transcriptions dépassent les 2 min par défaut du Bash de Claude Code.
    env.setdefault("BASH_DEFAULT_TIMEOUT_MS", "1200000")
    env.setdefault("BASH_MAX_TIMEOUT_MS", "1800000")
    # Par défaut on facture l'abonnement Claude (login CLI ou CLAUDE_CODE_OAUTH_TOKEN) :
    # une ANTHROPIC_API_KEY héritée prendrait sinon le dessus (facturation API).
    if os.getenv("CLAUDE_STUDIO_AUTH", "subscription") != "api_key":
        env.pop("ANTHROPIC_API_KEY", None)
    return env


class StreamParser:
    """Transforme le stream-json de Claude Code en événements de haut niveau.

    Événements : `agent_start` / `agent_end` (sous-agents des 5 rôles), `tool`
    (appel d'outil, avec le rôle courant), `result` (fin de session).
    """

    def __init__(self) -> None:
        self.agents: dict[str, str] = {}  # tool_use_id → rôle
        self.result: dict[str, Any] | None = None

    def feed(self, line: str) -> list[tuple[str, dict[str, Any]]]:
        line = line.strip()
        if not line:
            return []
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return []
        events: list[tuple[str, dict[str, Any]]] = []
        mtype = msg.get("type")
        parent = msg.get("parent_tool_use_id")
        message = msg.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if mtype == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name", "")
                tool_input = block.get("input") or {}
                if name in SUBAGENT_TOOLS:
                    role = str(tool_input.get("subagent_type") or "general")
                    self.agents[block["id"]] = role
                    events.append(("agent_start", {
                        "id": block["id"],
                        "role": role,
                        "description": tool_input.get("description", ""),
                        "prompt": tool_input.get("prompt", ""),
                    }))
                else:
                    events.append(("tool", {
                        "role": self.agents.get(parent or "", "producteur"),
                        "name": name,
                        "input": tool_input,
                    }))
        elif mtype == "user" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tool_id = block.get("tool_use_id", "")
                if tool_id in self.agents:
                    events.append(("agent_end", {
                        "id": tool_id,
                        "role": self.agents[tool_id],
                        "is_error": bool(block.get("is_error")),
                        "output": _tool_result_text(block.get("content")),
                    }))
        elif mtype == "system" and msg.get("subtype") == "permission_denied":
            events.append(("denied", {
                "role": self.agents.get(parent or "", "producteur"),
                "name": msg.get("tool_name", ""),
            }))
        elif mtype == "result":
            self.result = msg
            events.append(("result", msg))
        return events


_HANDBACK_MARKER = "The report follows:"
_TRAILER_PREFIXES = ("agentId:", "<usage>", "subagent_tokens:", "tool_uses:", "duration_ms:")


def _tool_result_text(content: Any) -> str:
    if isinstance(content, list):
        content = "\n".join(
            str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content
        )
    if not isinstance(content, str):
        return ""
    # Retire l'en-tête et le pied ajoutés par Claude Code autour du rapport d'un sous-agent.
    if _HANDBACK_MARKER in content:
        content = content.split(_HANDBACK_MARKER, 1)[1]
    lines = [line.strip() for line in content.splitlines()]
    return "\n".join(
        line for line in lines if not line.startswith(_TRAILER_PREFIXES) and line != "</usage>"
    ).strip()


class ClaudeRunError(RuntimeError):
    pass


async def run_claude(
    run_dir: Path,
    *,
    cfg: LaunchConfig | None = None,
    on_event: EventHandler | None = None,
    prompt: str = "/make-video",
) -> dict[str, Any]:
    """Exécute la session et renvoie l'événement `result` final de Claude Code."""
    from agent.core.subprocess_registry import register, terminate_proc, unregister

    cfg = cfg or LaunchConfig()
    if shutil.which(cfg.claude_bin) is None:
        raise ClaudeRunError(f"CLI Claude introuvable : {cfg.claude_bin} (npm i -g @anthropic-ai/claude-code)")
    log_path = run_dir / "claude_stream.jsonl"
    stderr_path = run_dir / "claude_stderr.log"
    parser = StreamParser()

    with stderr_path.open("wb") as stderr_fh:
        proc = await asyncio.create_subprocess_exec(
            *build_command(cfg, prompt),
            cwd=str(run_dir),
            env=build_env(run_dir),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr_fh,
            limit=_STREAM_LIMIT,
        )
        register(proc)
        try:
            async def _pump() -> None:
                assert proc.stdout is not None
                with log_path.open("a", encoding="utf-8") as log_fh:
                    async for raw in proc.stdout:
                        line = raw.decode("utf-8", errors="replace")
                        log_fh.write(line)
                        try:
                            events = parser.feed(line)
                            for kind, data in events:
                                if on_event:
                                    await on_event(kind, data)
                        except Exception:
                            # Le suivi est best effort : il ne doit jamais tuer la session.
                            logger.exception("Événement stream-json non traité")
                await proc.wait()

            await asyncio.wait_for(_pump(), timeout=cfg.timeout_s)
        except asyncio.TimeoutError as exc:
            await terminate_proc(proc)
            raise ClaudeRunError(f"session Claude interrompue après {cfg.timeout_s:.0f}s") from exc
        except BaseException:
            await terminate_proc(proc)
            raise
        finally:
            unregister(proc)

    if parser.result is None:
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-800:]
        raise ClaudeRunError(f"Claude s'est arrêté sans résultat (code {proc.returncode}) : {tail}")
    if parser.result.get("is_error"):
        raise ClaudeRunError(
            f"session Claude en erreur ({parser.result.get('subtype')}) : "
            f"{str(parser.result.get('result') or '')[:500]}"
        )
    return parser.result
