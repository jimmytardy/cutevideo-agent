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
from typing import TYPE_CHECKING, Any
from collections.abc import Awaitable, Callable

from agent.core.env import env_float, env_int, env_optional_float
from agent.skills.media_sources.ai.registry import provider_family
from studio.agent_stream import stream_lines
from studio.assets import DEFAULT_AI_MODEL, max_ai_images
from studio.contracts import Brief
from studio.user_keys import INHERITED_SECRET_VARS, studio_env

if TYPE_CHECKING:
    from agent.core.api_keys import UserKeys

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_TEMPLATE = Path(__file__).resolve().parent / "workspace"
ROLES = ("scenariste", "critique-scenario", "voix", "monteur", "miniaturiste", "critique")
SUBAGENT_TOOLS = ("Agent", "Task")
# Passées en ligne de commande : les permissions d'un .claude/settings.json sont
# ignorées tant que le dossier n'a pas été marqué « de confiance » interactivement.
# Recherche web : autorisée pour la session, mais seul le scénariste la reçoit (`tools:` de son frontmatter) pour
# vérifier ses faits. Le Bash reste limité aux outils Studio et l'environnement est purgé de ses secrets.
WEB_TOOLS = ("WebSearch", "WebFetch")
ALLOWED_TOOLS = ("Bash(python -m studio.tools:*)", "Read", "Write", "Edit", "Glob", *WEB_TOOLS, *SUBAGENT_TOOLS)
DISALLOWED_TOOLS: tuple[str, ...] = ()
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
    shutil.copytree(WORKSPACE_TEMPLATE / "docs", run_dir / "docs", dirs_exist_ok=True)
    (run_dir / "brief.json").write_text(
        brief.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
    )
    return run_dir


def _session_timeout() -> float | None:
    """Durée max de la session Claude (`CLAUDE_STUDIO_TIMEOUT_S`, en s) ; 0 ou moins = pas de limite."""
    value = env_float("CLAUDE_STUDIO_TIMEOUT_S", 3600.0)
    return value if value > 0 else None


@dataclass
class LaunchConfig:
    model: str = field(default_factory=lambda: os.getenv("CLAUDE_STUDIO_MODEL", "claude-opus-5-5"))
    timeout_s: float | None = field(default_factory=_session_timeout)
    max_turns: int = field(default_factory=lambda: env_int("CLAUDE_STUDIO_MAX_TURNS", 400, minimum=1))
    max_budget_usd: float | None = field(
        default_factory=lambda: env_optional_float("CLAUDE_STUDIO_MAX_BUDGET_USD")
    )
    claude_bin: str = field(default_factory=lambda: os.getenv("CLAUDE_BIN", "claude"))


def permission_args() -> list[str]:
    args = ["--allowedTools", *ALLOWED_TOOLS]
    return [*args, "--disallowedTools", *DISALLOWED_TOOLS] if DISALLOWED_TOOLS else args


def build_command(
    cfg: LaunchConfig,
    prompt: str = "/make-video",
    *,
    session_id: str | None = None,
    resume: bool = False,
) -> list[str]:
    """Commande `claude -p`. `session_id` : session conservée (création) ou reprise (`resume=True`)."""
    cmd = [
        cfg.claude_bin, "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--model", cfg.model,
        "--max-turns", str(cfg.max_turns),
        *permission_args(),
        "--permission-mode", "dontAsk",
        # Ni hooks ni plugins utilisateur : seuls les réglages du run dir.
        "--setting-sources", "project",
    ]
    if session_id:
        # Transcription gardée dans CLAUDE_CONFIG_DIR : un worker redémarré reprend la session.
        cmd += ["--resume" if resume else "--session-id", session_id]
    else:
        cmd.append("--no-session-persistence")
    if cfg.max_budget_usd:
        cmd += ["--max-budget-usd", str(cfg.max_budget_usd)]
    return cmd


def _read_brief(run_dir: Path) -> Brief | None:
    try:
        return Brief.model_validate_json((run_dir / "brief.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def usable_ai_models(brief: Brief | None, keys: UserKeys | None) -> list[str]:
    """Modèles du brief (sinon `flux_2_dev`) dont le propriétaire a la clé : fal pour Flux,
    compte de service GCP pour Imagen 3."""
    if brief is None or brief.max_ai_images == 0 or keys is None:
        return []
    have = {"flux": bool(keys.fal), "google": bool(keys.gcp_credentials_json)}
    return [m for m in brief.ai_models or [DEFAULT_AI_MODEL] if have.get(provider_family(m))]


def build_env(
    run_dir: Path, keys: UserKeys | None = None, *, config_dir: Path | None = None
) -> dict[str, str]:
    """Environnement du CLI : aucune clé héritée, seulement celles de l'utilisateur (`keys`).

    `config_dir` isole l'état du CLI (`CLAUDE_CONFIG_DIR`) par utilisateur.
    """
    env = {name: value for name, value in os.environ.items() if name not in INHERITED_SECRET_VARS}
    if keys is not None:
        env.update(studio_env(keys))
    if config_dir is not None:
        config_dir.mkdir(parents=True, exist_ok=True)
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    python_bin = str(Path(sys.executable).parent)
    env["PATH"] = f"{python_bin}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH")]))
    env["STUDIO_RUN_DIR"] = str(run_dir)
    # Politiques lues ici, avant que Claude ne puisse toucher brief.json : les outils
    # (`animate*`, `ai-image`) ne font confiance qu'à ces variables.
    brief = _read_brief(run_dir)
    env["STUDIO_ANIMATIONS"] = brief.animations if brief else "off"
    env["STUDIO_VISUAL_STYLE"] = brief.visual_style if brief else "animation"
    if brief is None:
        env["STUDIO_MAX_AI_IMAGES"] = "0"
    elif brief.max_ai_images is not None:
        env["STUDIO_MAX_AI_IMAGES"] = str(min(brief.max_ai_images, max_ai_images()))
    env["STUDIO_AI_MODELS"] = ",".join(usable_ai_models(brief, keys))
    # Rendus et transcriptions dépassent les 2 min par défaut du Bash de Claude Code.
    env.setdefault("BASH_DEFAULT_TIMEOUT_MS", "1200000")
    env.setdefault("BASH_MAX_TIMEOUT_MS", "1800000")
    return env


class StreamParser:
    """Transforme le stream-json de Claude Code en événements de haut niveau.

    Événements : `agent_start` / `agent_end` (sous-agents des rôles de `ROLES`), `tool`
    (appel d'outil, avec le rôle courant), `agent_stream` (lignes de trace d'un
    sous-agent, cf. `studio.agent_stream`), `result` (fin de session).
    """

    def __init__(self, run_dir: str = "") -> None:
        self.run_dir = run_dir
        self.agents: dict[str, str] = {}  # tool_use_id → rôle
        self.result: dict[str, Any] | None = None
        # Dernier état des limites d'usage (`rate_limit_event` : status, resetsAt, rateLimitType).
        self.rate_limit: dict[str, Any] | None = None
        # Texte du message d'erreur synthétique de Claude Code sur une limite (`error: "rate_limit"`),
        # ex. « You've hit your session limit · resets 3:45pm » : le `result` final peut être vide.
        self.limit_message: str | None = None

    def feed(self, line: str) -> list[tuple[str, dict[str, Any]]]:
        line = line.strip()
        if not line:
            return []
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return []
        if not isinstance(msg, dict):
            return []
        events = self._events(msg)
        if msg.get("type") == "assistant" and msg.get("error") == "rate_limit":
            content = (msg.get("message") or {}).get("content")
            texts = [b.get("text", "") for b in content if isinstance(b, dict)] if isinstance(content, list) else []
            self.limit_message = " ".join(t for t in texts if t) or "rate_limit"
        agent_id = msg.get("parent_tool_use_id") or (
            msg.get("tool_use_id") if msg.get("subtype") == "task_progress" else None
        )
        if agent_id in self.agents:
            lines = stream_lines(msg, run_dir=self.run_dir, result_text=_tool_result_text)
            if lines:
                events.append(("agent_stream", {"id": agent_id, "role": self.agents[agent_id], "lines": lines}))
        return events

    def _events(self, msg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        mtype = msg.get("type")
        parent = msg.get("parent_tool_use_id") or ""
        message = msg.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        if mtype == "assistant":
            return [self._on_tool_use(b, parent) for b in blocks if b.get("type") == "tool_use"]
        if mtype == "user":
            return [
                self._on_agent_end(b)
                for b in blocks
                if b.get("type") == "tool_result" and b.get("tool_use_id", "") in self.agents
            ]
        if mtype == "system" and msg.get("subtype") == "permission_denied":
            return [("denied", {"role": self.agents.get(parent, "producteur"), "name": msg.get("tool_name", "")})]
        if mtype == "result":
            self.result = msg
            return [("result", msg)]
        if mtype == "rate_limit_event" and isinstance(msg.get("rate_limit_info"), dict):
            self.rate_limit = msg["rate_limit_info"]
        return []

    def _on_tool_use(self, block: dict[str, Any], parent: str) -> tuple[str, dict[str, Any]]:
        """Lancement d'un sous-agent (rôle) ou appel d'outil attribué au rôle qui l'a fait."""
        name = block.get("name", "")
        tool_input = block.get("input") or {}
        if name in SUBAGENT_TOOLS:
            role = str(tool_input.get("subagent_type") or "general")
            self.agents[block["id"]] = role
            return ("agent_start", {
                "id": block["id"],
                "role": role,
                "description": tool_input.get("description", ""),
                "prompt": tool_input.get("prompt", ""),
            })
        return ("tool", {"role": self.agents.get(parent, "producteur"), "name": name, "input": tool_input})

    def _on_agent_end(self, block: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        tool_id = block["tool_use_id"]
        return ("agent_end", {
            "id": tool_id,
            "role": self.agents[tool_id],
            "is_error": bool(block.get("is_error")),
            "output": _tool_result_text(block.get("content")),
        })


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


def error_detail(parser: StreamParser) -> str:
    """Texte d'une session terminée en erreur : `result`, sinon `errors`, sinon le message synthétique de
    Claude Code sur une limite d'usage (`result` est alors vide)."""
    result = parser.result or {}
    return str(result.get("result") or "; ".join(map(str, result.get("errors") or [])) or parser.limit_message or "")


class ClaudeRunError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        result: dict[str, Any] | None = None,
        rate_limit: dict[str, Any] | None = None,
        limit_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.rate_limit = rate_limit
        self.limit_message = limit_message

    @property
    def no_turn_played(self) -> bool:
        """Le CLI a répondu sans jouer un tour (ex. `--resume` d'une session introuvable : `num_turns: 0`).

        Une sortie sans résultat (crash, processus tué) n'en est pas une : relancer une session complète
        doublerait le coût d'une création déjà avancée."""
        return self.result is not None and not self.result.get("num_turns")


async def run_claude(
    run_dir: Path,
    *,
    cfg: LaunchConfig | None = None,
    on_event: EventHandler | None = None,
    prompt: str = "/make-video",
    keys: UserKeys | None = None,
    config_dir: Path | None = None,
    session_id: str | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Exécute la session avec les clés `keys` et renvoie l'événement `result` final de Claude Code."""
    from agent.core.subprocess_registry import register, terminate_proc, unregister

    cfg = cfg or LaunchConfig()
    if shutil.which(cfg.claude_bin) is None:
        raise ClaudeRunError(f"CLI Claude introuvable : {cfg.claude_bin} (npm i -g @anthropic-ai/claude-code)")
    log_path = run_dir / "claude_stream.jsonl"
    stderr_path = run_dir / "claude_stderr.log"
    parser = StreamParser(str(run_dir))

    with stderr_path.open("wb") as stderr_fh:
        proc = await asyncio.create_subprocess_exec(
            *build_command(cfg, prompt, session_id=session_id, resume=resume),
            cwd=str(run_dir),
            env=build_env(run_dir, keys, config_dir=config_dir),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr_fh,
            limit=_STREAM_LIMIT,
            # Groupe de processus dédié : l'annulation tue aussi outils, ffmpeg et Chromium.
            start_new_session=True,
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
        except TimeoutError as exc:
            await terminate_proc(proc)
            raise ClaudeRunError(f"session Claude interrompue après {cfg.timeout_s:.0f}s") from exc
        except BaseException:
            await terminate_proc(proc)
            raise
        finally:
            unregister(proc)

    if parser.result is None:
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-800:]
        raise ClaudeRunError(
            f"Claude s'est arrêté sans résultat (code {proc.returncode}) : {tail}",
            rate_limit=parser.rate_limit,
            limit_message=parser.limit_message,
        )
    if parser.result.get("is_error"):
        raise ClaudeRunError(
            f"session Claude en erreur ({parser.result.get('subtype')}) : {error_detail(parser)[:500]}",
            result=parser.result,
            rate_limit=parser.rate_limit,
            limit_message=parser.limit_message,
        )
    return parser.result
