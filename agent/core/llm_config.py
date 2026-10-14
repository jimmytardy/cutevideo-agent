from __future__ import annotations

from datetime import date
from typing import Any

from agent.core.config import load_agent_config

DEFAULT_MODEL = "claude-opus-5-5"
ECONOMY_MODEL = "claude-sonnet-5-5"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_PLANNER_LLM_WEEKDAYS = [0, 3]


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


def planner_llm_weekdays() -> list[int]:
    cfg = _llm_cfg()
    raw = cfg.get("planner_llm_weekdays", DEFAULT_PLANNER_LLM_WEEKDAYS)
    return [int(d) for d in raw]


def is_planner_llm_day(day: date | None = None) -> bool:
    d = day or date.today()
    return d.weekday() in planner_llm_weekdays()
