"""Reprise d'une création Claude Studio interrompue par un redémarrage du worker.

L'état vit dans `Project.config["claude_studio_session"]` : `session_id` (session Claude Code conservée
pour `--resume`), `resumes` (reprises consécutives sans progrès), `total_resumes`, `progress` (nombre
d'étapes réussies lors de la dernière reprise). Garde-fous : une reprise n'est tentée que si le run dir
existe encore, et la création est abandonnée après `STUDIO_MAX_RESUMES` reprises d'affilée sans nouvelle
étape réussie ou `STUDIO_MAX_RESUMES_TOTAL` reprises au total — un worker qui redémarre en boucle ne
relance donc pas la même création indéfiniment.

Limite d'usage de l'abonnement Claude (mode CLI) : la création est mise en pause (`paused_until`,
`limit_pauses`) jusqu'au reset annoncé par Claude Code, puis reprise de la même façon, au plus
`STUDIO_MAX_LIMIT_PAUSES` fois. Ces pauses ne comptent pas comme des reprises de worker.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from agent.core.env import env_int

CONFIG_KEY = "claude_studio_session"
INTERRUPTED_MESSAGE = "Worker redémarré — reprise automatique"
LIMIT_MESSAGE = "Limite d'usage Claude atteinte"

# Reprise jamais avant ce délai (reset déjà passé ou imprécis) ni sans marge après le reset annoncé.
MIN_PAUSE_S = 120
RESET_MARGIN_S = 60
# Phrases de Claude Code pour la limite de l'abonnement, cherchées dans la réponse du CLI seulement (pas dans
# stderr, où un « 429 » ou « limit reached » quelconque déclencherait une fausse pause).
# Formes réelles : « You've hit your session limit · resets 3:45pm », « …weekly / Opus limit… »,
# « You're out of extra usage · resets 6:40pm », « Claude AI usage limit reached|<epoch> ».
_LIMIT_TEXT = re.compile(
    r"usage limit|hit your (?:\w+ )*limit|out of extra usage|rate_limit_error", re.IGNORECASE
)
_LIMIT_RESET_EPOCH = re.compile(r"limit reached\|(\d{9,})", re.IGNORECASE)
_USER_LIMIT_KEY = "claude_limit:{user_id}"


def max_resumes() -> int:
    return env_int("STUDIO_MAX_RESUMES", 3, minimum=0)


def max_total_resumes() -> int:
    return env_int("STUDIO_MAX_RESUMES_TOTAL", 10, minimum=0)


def max_limit_pauses() -> int:
    return env_int("STUDIO_MAX_LIMIT_PAUSES", 6, minimum=0)


def default_limit_wait_s() -> int:
    return env_int("STUDIO_LIMIT_DEFAULT_WAIT_S", 1800, minimum=MIN_PAUSE_S)


class StudioPaused(Exception):
    """Création en pause (limite d'usage Claude) jusqu'à `until` ; reprise par le worker."""

    def __init__(self, until: datetime) -> None:
        super().__init__(f"{LIMIT_MESSAGE} : pause jusqu'à {until.isoformat()}")
        self.until = until


@dataclass(frozen=True)
class ResumeDecision:
    action: Literal["fresh", "resume", "give_up"]
    state: dict[str, Any]
    reason: str = ""


def run_dir_resumable(run_dir: Path) -> bool:
    return (run_dir / "brief.json").is_file()


def decide(state: dict[str, Any] | None, *, progress: int, run_dir_ok: bool) -> ResumeDecision:
    """Reprendre, repartir de zéro (rien à reprendre) ou abandonner (trop d'interruptions)."""
    state = dict(state or {})
    if not state.get("session_id") or not run_dir_ok:
        return ResumeDecision("fresh", {}, "rien à reprendre")
    if state.pop("paused_until", None):
        # Fin d'une pause sur limite d'usage : plafonnée par `limit_pauses`, pas par les reprises de worker.
        # La progression est notée pour qu'un redémarrage ultérieur ne remette pas le compteur à zéro à tort.
        state["progress"] = max(progress, int(state.get("progress", 0)))
        return ResumeDecision("resume", state, "reprise après la limite d'usage Claude")
    resumes = int(state.get("resumes", 0))
    if progress > int(state.get("progress", 0)):
        resumes = 0
    resumes += 1
    total = int(state.get("total_resumes", 0)) + 1
    if resumes > max_resumes():
        return ResumeDecision(
            "give_up", state, f"Reprise automatique abandonnée : {resumes - 1} interruptions sans progrès"
        )
    if total > max_total_resumes():
        return ResumeDecision("give_up", state, f"Reprise automatique abandonnée : {total - 1} reprises au total")
    state.update(
        resumes=resumes,
        total_resumes=total,
        progress=progress,
        last_resume_at=datetime.now(UTC).isoformat(),
    )
    return ResumeDecision("resume", state, f"reprise {resumes}/{max_resumes()}")


def usage_limit_reset(exc: BaseException, *, now: datetime | None = None) -> datetime | None:
    """Heure de reprise si `exc` (ClaudeRunError) vient d'une limite d'usage, sinon None.

    Limite reconnue au dernier `rate_limit_event` refusé ou au texte de l'erreur ; heure = `resetsAt`
    (ou l'epoch de « …limit reached|<epoch> ») + marge, à défaut maintenant + `STUDIO_LIMIT_DEFAULT_WAIT_S`.
    """
    now = now or datetime.now(UTC)
    rate_limit = getattr(exc, "rate_limit", None) or {}
    result = getattr(exc, "result", None) or {}
    limit_message = getattr(exc, "limit_message", None)
    text = " ".join([str(result.get("result") or ""), *map(str, result.get("errors") or []), limit_message or ""])
    # Le message synthétique (`error: "rate_limit"`) ne suffit pas seul : un ralentissement serveur temporaire
    # en produit aussi. Il compte s'il porte un texte de limite d'abonnement (« You've hit your session limit… »).
    if rate_limit.get("status") != "rejected" and not _LIMIT_TEXT.search(text):
        return None
    epoch_match = _LIMIT_RESET_EPOCH.search(text)
    epoch = rate_limit.get("resetsAt") or (epoch_match.group(1) if epoch_match else None)
    try:
        seconds = int(epoch) if epoch else None
        if seconds and seconds > 10**11:  # millisecondes (certains SDK) plutôt que secondes
            seconds //= 1000
        reset = datetime.fromtimestamp(seconds, UTC) + timedelta(seconds=RESET_MARGIN_S) if seconds else None
    except (TypeError, ValueError, OverflowError, OSError):
        reset = None
    reset = reset or now + timedelta(seconds=default_limit_wait_s())
    return max(reset, now + timedelta(seconds=MIN_PAUSE_S))


def is_usage_limit_text(text: str) -> bool:
    """Message de limite d'usage (ex. rapport d'un sous-agent « Agent terminated early due to an API error… »)."""
    return bool(_LIMIT_TEXT.search(text or ""))


def record_pause(state: dict[str, Any] | None, until: datetime) -> tuple[bool, dict[str, Any]]:
    """Ajoute une pause à l'état ; False si le plafond `STUDIO_MAX_LIMIT_PAUSES` est dépassé."""
    state = dict(state or {})
    state["limit_pauses"] = int(state.get("limit_pauses", 0)) + 1
    state["paused_until"] = until.isoformat()
    return state["limit_pauses"] <= max_limit_pauses(), state


def paused_until(state: dict[str, Any] | None) -> datetime | None:
    raw = (state or {}).get("paused_until")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


async def set_user_limit(user_id: uuid.UUID, until: datetime) -> None:
    """Limite du compte Claude connue jusqu'à `until` : les autres créations attendent sans appeler Claude."""
    from agent.core.queue import queue

    current = await get_user_limit(user_id)
    if current and current > until:  # une autre création connaît déjà un reset plus lointain
        return
    ttl = max(1, int((until - datetime.now(UTC)).total_seconds()))
    await queue.client.set(_USER_LIMIT_KEY.format(user_id=user_id), until.isoformat(), ex=ttl)


async def get_user_limit(user_id: uuid.UUID) -> datetime | None:
    from agent.core.queue import queue

    await queue.connect()
    return paused_until({"paused_until": await queue.client.get(_USER_LIMIT_KEY.format(user_id=user_id))})
