from __future__ import annotations

from datetime import date
from typing import Any

from typing import TYPE_CHECKING

from agent.core.config import load_agent_config

if TYPE_CHECKING:
    from agent.core.learning_context import ChannelContextSnapshot

DEFAULT_MODEL = "claude-opus-4-5"
ECONOMY_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_ENGAGEMENT_WEEKDAYS = [0, 3]
DEFAULT_PLANNER_LLM_WEEKDAYS = [0, 3]
DEFAULT_MAX_INSIGHTS = 8
DEFAULT_MAX_PUBLICATIONS_PER_RUN = 40


def _llm_cfg() -> dict[str, Any]:
    return load_agent_config().get("llm", {})


def resolve_model(agent_name: str) -> str:
    cfg = _llm_cfg()
    default_model = str(cfg.get("default_model", DEFAULT_MODEL))
    economy_model = str(cfg.get("economy_model", ECONOMY_MODEL))
    agent_models: dict[str, str] = cfg.get("agent_models", {}) or {}
    tier = agent_models.get(agent_name, "default")
    if tier == "economy":
        return economy_model
    if tier.startswith("claude-"):
        return tier
    return default_model


def resolve_max_tokens(agent_name: str, override: int | None = None) -> int:
    if override is not None:
        return override
    cfg = _llm_cfg()
    per_agent: dict[str, int] = cfg.get("max_tokens", {}) or {}
    if agent_name in per_agent:
        return int(per_agent[agent_name])
    return DEFAULT_MAX_TOKENS


def engagement_run_weekdays() -> list[int]:
    cfg = _llm_cfg()
    raw = cfg.get("engagement_run_weekdays", DEFAULT_ENGAGEMENT_WEEKDAYS)
    return [int(d) for d in raw]


def planner_llm_weekdays() -> list[int]:
    cfg = _llm_cfg()
    raw = cfg.get("planner_llm_weekdays", DEFAULT_PLANNER_LLM_WEEKDAYS)
    return [int(d) for d in raw]


def is_engagement_run_day(day: date | None = None) -> bool:
    d = day or date.today()
    return d.weekday() in engagement_run_weekdays()


def is_planner_llm_day(day: date | None = None) -> bool:
    d = day or date.today()
    return d.weekday() in planner_llm_weekdays()


def learning_context_max_insights() -> int:
    return int(_llm_cfg().get("learning_context_max_insights", DEFAULT_MAX_INSIGHTS))


def max_publications_per_engagement_run() -> int:
    engagement = load_agent_config().get("engagement", {})
    llm = _llm_cfg()
    return int(
        engagement.get(
            "max_publications_per_engagement_run",
            llm.get("max_publications_per_engagement_run", DEFAULT_MAX_PUBLICATIONS_PER_RUN),
        )
    )


def analytics_thresholds() -> dict[str, float]:
    engagement = load_agent_config().get("engagement", {})
    analytics = engagement.get("analytics_thresholds", {})
    return {
        "views_success_pct": float(analytics.get("views_success_pct", 20.0)),
        "views_underperform_pct": float(analytics.get("views_underperform_pct", -10.0)),
    }


def compact_learning_context(snapshot: "ChannelContextSnapshot") -> str:
    """Résumé court pour prompts et cache (top insights actifs)."""
    max_n = learning_context_max_insights()
    if not snapshot.summary and not snapshot.active_insights():
        return "Aucun retour audience ou analytics enregistré pour cette chaîne."

    lines: list[str] = []
    if snapshot.summary:
        summary = snapshot.summary.strip()
        if len(summary) > 600:
            summary = summary[:597] + "..."
        lines.append(f"Résumé : {summary}")

    active = snapshot.active_insights()[:max_n]
    if active:
        lines.append("Insights actifs :")
        for ins in active:
            lines.append(
                f"- [{ins.source}] (conf. {ins.confidence:.2f}) {ins.text}"
                + (f" — {ins.evidence}" if ins.evidence else "")
            )
    return "\n".join(lines)
