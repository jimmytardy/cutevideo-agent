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
# Explicite ce que le mode headless refuserait de toute façon faute d'approbation : sans outil de mise à
# mort, l'agent ne peut pas faire déclarer une de ses tâches `killed` et forger le signal de reprise
# (cf. `background_tasks_stopped`). `KillShell` et `KillBash` sont les deux alias de `TaskStop` : on les
# nomme tous, rien ne garantissant qu'un refus sur l'outil couvre ses alias. `--disallowedTools` n'est passé
# que si ce tuple est non vide.
DISALLOWED_TOOLS: tuple[str, ...] = ("TaskStop", "KillShell", "KillBash")
# Événements `system` qui décrivent les tâches de fond de Claude Code (cf. `StreamParser._on_background`).
_BACKGROUND_SUBTYPES = ("background_tasks_changed", "task_started", "task_updated", "task_notification")
# Message du CLI quand ce plafond est atteint et qu'il tue ses tâches de fond.
_BG_CEILING_MARKER = "Background tasks still running"
# Journal stderr du CLI : écrit par `run_claude()`, relu par `background_tasks_stopped()`.
_STDERR_LOG = "claude_stderr.log"
# Silence du flux stream-json au-delà duquel la session est tenue pour bloquée (cf. `_stall_timeout`).
STALL_TIMEOUT_DEFAULT_S = 3600.0
# Libellé de tâche de fond : tronqué, il finit dans `Project.error_message` affiché au dashboard.
_LABEL_MAX = 200
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
    """Durée max de la session Claude (`CLAUDE_STUDIO_TIMEOUT_S`, en s) ; 0 ou moins = pas de limite.

    Sans limite par défaut : un rôle prend le temps qu'il faut, et c'est `_stall_timeout()` qui rattrape un
    blocage réel. Un plafond absolu couperait un montage animé en plein travail, en `failed` non reprenable.
    Si vous en reposez un, gardez-le **nettement supérieur** au seuil d'inactivité, sinon il se déclenche le
    premier et le watchdog ne peut jamais agir.
    """
    value = env_float("CLAUDE_STUDIO_TIMEOUT_S", 0.0)
    return value if value > 0 else None


def _stall_timeout() -> float | None:
    """Silence toléré sur le flux (`STUDIO_STALL_TIMEOUT_S`, en s) ; 0 ou moins = pas de surveillance.

    On ne borne pas la durée de travail d'un rôle — un montage animé dure des heures — mais le silence :
    tant qu'un sous-agent travaille, le flux porte des événements (`tool`, `agent_stream`, `task_progress`).

    Limite connue : une commande Bash passée en tâche de fond, elle, n'émet rien pendant son exécution
    (mesuré sur un run réel) et peut aller jusqu'à 2 h. Un rôle qui en lance une seule et attend pourrait
    donc être coupé en plein travail légitime ; relever le seuil au-delà de 2 h si le cas se présente. Le
    coût d'un faux positif reste borné à une reprise, pas à un échec.
    """
    value = env_float("STUDIO_STALL_TIMEOUT_S", STALL_TIMEOUT_DEFAULT_S)
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
    run_dir: Path, keys: UserKeys | None = None, *, config_dir: Path | None = None, policy: Brief | None = None
) -> dict[str, str]:
    """Environnement du CLI : aucune clé héritée, seulement celles de l'utilisateur (`keys`).

    `config_dir` isole l'état du CLI (`CLAUDE_CONFIG_DIR`) par utilisateur. `policy` : le brief recalculé
    depuis la base (chaîne + abonnement) ; sans lui (`studio.run`), `brief.json` est relu.
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
    # Politiques que les outils (`animate*`, `ai-image`) lisent, à l'exclusion de brief.json. Elles viennent du
    # brief recalculé par le runner : `brief.json` est modifiable par Claude, et une reprise (`--resume`) le
    # relirait après coup — la 3D, réservée aux abonnements payants, ne doit pas pouvoir s'y obtenir.
    brief = policy or _read_brief(run_dir)
    env["STUDIO_ANIMATIONS"] = brief.animations if brief else "off"
    env["STUDIO_VISUAL_STYLE"] = brief.visual_style if brief else "animation"
    env["STUDIO_MOTION3D"] = "1" if brief and brief.motion3d else "0"
    if brief is None:
        env["STUDIO_MAX_AI_IMAGES"] = "0"
    elif brief.max_ai_images is not None:
        env["STUDIO_MAX_AI_IMAGES"] = str(min(brief.max_ai_images, max_ai_images()))
    env["STUDIO_AI_MODELS"] = ",".join(usable_ai_models(brief, keys))
    # Rendus et transcriptions dépassent les 2 min par défaut du Bash de Claude Code ; un plan 3D peut prendre
    # jusqu'à ~20 min (rendu + file + encodage), d'où 30 min quand la 3D est active.
    env.setdefault("BASH_DEFAULT_TIMEOUT_MS", "1200000")
    if env["STUDIO_MOTION3D"] == "1":
        # Au moins 30 min, même si l'environnement en hérite un plus court.
        env["BASH_DEFAULT_TIMEOUT_MS"] = str(max(env_int("BASH_DEFAULT_TIMEOUT_MS", 0), 1800000))
    env.setdefault("BASH_MAX_TIMEOUT_MS", "1800000")
    # Ce plafond compte l'attente *inactive* et repart à chaque tour de Claude ; or le producteur devient
    # inactif dès qu'il a lancé un rôle, si bien que ses 10 min devenaient le budget du rôle — un montage qui
    # rend ses animations une par une (sandbox séquentiel) s'y faisait tuer en plein travail. On retire la
    # limite : un rôle prend le temps qu'il faut. Ce qui borne encore un blocage : 300 s par job de sandbox et
    # le délai propre à chaque commande Bash (variables ci-dessus au premier plan ; une commande passée en
    # tâche de fond garde le sien, plafonné à 2 h). Ce qui ne le borne PAS : `run_ffmpeg(timeout_s=…)`, que
    # seul l'encodage par clip de `studio/render.py` renseigne, et `--max-turns`, qui compte des tours et non
    # du temps. Il n'y a donc plus de plafond au niveau de la session (`CLAUDE_STUDIO_TIMEOUT_S=0`) : c'est
    # `_stall_timeout()` qui rattrape un blocage réel, en coupant la session sur un silence prolongé du flux.
    env.setdefault("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "0")
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
        # Tâches de fond tuées par Claude Code au plafond d'attente : la session se termine « avec succès »
        # sans avoir fini le travail. `task_id → libellé`, le libellé arrivant parfois après la mise à mort.
        self.killed_task_ids: set[str] = set()
        self.task_labels: dict[str, str] = {}
        # Sous-agents exécutés en tâche de fond : leur `tool_result` arrive aussitôt et ne dit rien de
        # leur travail. `task_started` les annonce avant cet accusé, ce qui permet de l'ignorer.
        self.background_agents: set[str] = set()
        # Accusés mis de côté : si le CLI cessait d'émettre ses notifications, ils reprennent du service
        # comme fin d'étape (cf. `_reconcile_background_agents`).
        self.background_acks: dict[str, str] = {}
        self.saw_task_notification = False

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
                event
                for b in blocks
                if b.get("type") == "tool_result" and b.get("tool_use_id", "") in self.agents
                if (event := self._on_agent_tool_result(b)) is not None
            ]
        if mtype == "system" and msg.get("subtype") == "permission_denied":
            return [("denied", {"role": self.agents.get(parent, "producteur"), "name": msg.get("tool_name", "")})]
        if mtype == "system" and msg.get("subtype") in _BACKGROUND_SUBTYPES:
            return self._on_background(msg)
        if mtype == "result":
            self.result = msg
            return [*self._reconcile_background_agents(), ("result", msg)]
        if mtype == "rate_limit_event" and isinstance(msg.get("rate_limit_info"), dict):
            self.rate_limit = msg["rate_limit_info"]
        return []

    def _on_background(self, msg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Suit le cycle de vie des tâches de fond du CLI.

        Deux rôles. D'abord la fin réelle d'un sous-agent : `task_started` l'annonce (avec son
        `tool_use_id`) **avant** l'accusé de lancement, et `task_notification` `completed` porte son vrai
        rapport — sans quoi l'étape serait close dès le lancement, avec une durée nulle.
        Les deux signaux de clôture sont exclusifs : `background_agents` décide lequel vaut pour un
        sous-agent donné, de sorte qu'il en reçoive toujours exactement un. Un statut autre que
        `completed` (`stopped` sur une tâche tuée) n'en est pas un : l'étape reste ouverte et c'est
        `close_dangling()` qui la clôt avec le statut que le contexte impose.
        Ensuite le libellé des tâches tuées (`task_updated` + `killed`), qui enrichit le message
        d'interruption ; c'est `background_tasks_stopped()` qui décide si la session s'est arrêtée en
        plein travail.
        """
        events: list[tuple[str, dict[str, Any]]] = []
        if msg.get("subtype") == "task_notification":
            self.saw_task_notification = True
        tool_use_id = str(msg.get("tool_use_id") or "")
        if tool_use_id in self.agents:
            if msg.get("subtype") == "task_started":
                self.background_agents.add(tool_use_id)
            elif (
                msg.get("subtype") == "task_notification"
                and msg.get("status") == "completed"
                and tool_use_id in self.background_agents
            ):
                self.background_acks.pop(tool_use_id, None)
                events.append(("agent_end", {
                    "id": tool_use_id,
                    "role": self.agents[tool_use_id],
                    "is_error": False,
                    "output": _tool_result_text(msg.get("summary")),
                }))
        # `background_tasks_changed` liste ses tâches dans `tasks`, tandis que `task_started` porte
        # `description` / `subagent_type` à la racine du message : `msg` est donc lui-même un porteur.
        for task in (*(msg.get("tasks") or []), msg):
            if not isinstance(task, dict):
                continue
            label = str(task.get("description") or task.get("subagent_type") or "")[:_LABEL_MAX]
            if label and (task_id := str(task.get("task_id") or "")):
                self.task_labels[task_id] = label
        task_id = str(msg.get("task_id") or "")
        if not task_id:
            return events
        if summary := msg.get("summary"):
            # Repli moins précis qu'une `description` : il ne doit jamais l'écraser.
            self.task_labels.setdefault(task_id, str(summary)[:_LABEL_MAX])
        if (msg.get("patch") or {}).get("status") == "killed":
            self.killed_task_ids.add(task_id)
        if task_id not in self.killed_task_ids:
            return events
        # Le libellé peut arriver après la mise à mort : on réémet l'événement pour l'enrichir.
        events.append(("task_killed", {"id": task_id, "label": self.task_labels.get(task_id, "")}))
        return events

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

    def _on_agent_tool_result(self, block: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Fin d'un sous-agent telle que la rend l'outil `Task`, ou `None` si ce n'est qu'un accusé.

        En tâche de fond, le `tool_result` d'un succès arrive aussitôt et ne dit rien du travail : le vrai
        rapport viendra par `task_notification` (cf. `_on_background`). Une **erreur**, elle, n'arrive que
        par ce `tool_result` — c'est le seul porteur du message d'échec, dont dépend la détection d'une
        limite d'usage (`_ProgressRecorder.limit_failures`) : la filtrer la rendrait muette.
        """
        tool_id = block["tool_use_id"]
        if tool_id in self.background_agents and not block.get("is_error"):
            self.background_acks[tool_id] = _tool_result_text(block.get("content"))
            return None
        self.background_acks.pop(tool_id, None)
        return self._on_agent_end(block)

    def _reconcile_background_agents(self) -> list[tuple[str, dict[str, Any]]]:
        """Repli de fin de session si le CLI n'a émis aucune notification de tâche.

        Les accusés mis de côté ne sont repris que dans ce cas précis : le mécanisme s'est tu pour tout le
        monde, donc le contrat du CLI a changé. On revient alors à l'ancien comportement — des étapes de
        durée nulle — plutôt que de laisser `close_dangling()` marquer en échec les étapes d'une création
        réussie, et surtout plutôt que de laisser le compteur de progrès à zéro, ce qui ferait abandonner
        au plafond `STUDIO_MAX_RESUMES` une création qui avance.

        Une seule notification reçue suffit à écarter ce repli : une étape restée ouverte malgré un
        mécanisme qui fonctionne n'a réellement pas fini (tâche tuée, notifiée `stopped`), et c'est
        `close_dangling()` qui doit la clore.
        """
        if self.saw_task_notification or not self.background_acks:
            return []
        logger.warning(
            "Claude Code n'a notifié aucune tâche de fond : %d étape(s) closes sur leur accusé de lancement",
            len(self.background_acks),
        )
        acks, self.background_acks = self.background_acks, {}
        return [
            ("agent_end", {"id": tool_id, "role": self.agents[tool_id], "is_error": False, "output": ack})
            for tool_id, ack in acks.items()
            if tool_id in self.agents
        ]

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


def background_tasks_stopped(run_dir: Path) -> bool:
    """Le CLI a annoncé sur stderr avoir tué ses tâches de fond au plafond d'attente.

    Discriminant volontairement étroit : seules ces sessions-là se sont arrêtées en plein travail et
    méritent une reprise. Une tâche de fond tuée pour une autre raison (pression mémoire) reste un échec
    normal, et un message du CLI qui changerait de formulation nous ramène simplement à ce comportement.
    """
    try:
        stderr = (run_dir / _STDERR_LOG).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _BG_CEILING_MARKER in stderr


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
        stalled: bool = False,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.rate_limit = rate_limit
        self.limit_message = limit_message
        # Session coupée sur un silence prolongé : reprenable, contrairement à une erreur de Claude.
        self.stalled = stalled

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
    policy: Brief | None = None,
) -> dict[str, Any]:
    """Exécute la session avec les clés `keys` et renvoie l'événement `result` final de Claude Code."""
    from agent.core.subprocess_registry import register, terminate_proc, unregister

    cfg = cfg or LaunchConfig()
    if shutil.which(cfg.claude_bin) is None:
        raise ClaudeRunError(f"CLI Claude introuvable : {cfg.claude_bin} (npm i -g @anthropic-ai/claude-code)")
    log_path = run_dir / "claude_stream.jsonl"
    stderr_path = run_dir / _STDERR_LOG
    parser = StreamParser(str(run_dir))

    with stderr_path.open("wb") as stderr_fh:
        proc = await asyncio.create_subprocess_exec(
            *build_command(cfg, prompt, session_id=session_id, resume=resume),
            cwd=str(run_dir),
            env=build_env(run_dir, keys, config_dir=config_dir, policy=policy),
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
                stall_s = _stall_timeout()
                with log_path.open("a", encoding="utf-8") as log_fh:
                    while True:
                        # `readline()` sous délai plutôt que `async for` : chaque lecture mesure le silence
                        # écoulé depuis la ligne précédente, et toute ligne reçue réarme le compteur.
                        try:
                            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=stall_s)
                        except TimeoutError:
                            # `stalled` = reprenable, contrairement au délai global de session, dont le
                            # `TimeoutError` est levé un cran plus haut par `wait_for(_pump())`. Le
                            # `except BaseException` de sortie tue tout le groupe de processus (outils,
                            # ffmpeg, Chromium). `stall_s` est forcément un seuil réel ici : `None`
                            # désarmerait `wait_for`, qui n'expirerait alors jamais.
                            raise ClaudeRunError(
                                f"session Claude sans activité depuis {stall_s:.0f}s : tenue pour bloquée",
                                # Une limite d'usage atteinte juste avant le silence doit rester
                                # reconnaissable, sinon on reprend au lieu de mettre en pause.
                                rate_limit=parser.rate_limit,
                                limit_message=parser.limit_message,
                                stalled=True,
                            ) from None
                        if not raw:
                            break
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
