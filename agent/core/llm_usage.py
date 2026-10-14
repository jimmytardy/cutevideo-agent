from __future__ import annotations

import logging
from dataclasses import dataclass

from agent.core.config import load_agent_config

logger = logging.getLogger(__name__)


@dataclass
class LlmUsageRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def record_llm_usage(record: LlmUsageRecord) -> None:
    """Trace la consommation d'un appel LLM (planner / distribution)."""
    logger.info(
        "LLM %s : %d in / %d out tokens ≈ %.4f $",
        record.model,
        record.input_tokens,
        record.output_tokens,
        record.cost_usd,
    )


def load_pricing() -> dict[str, dict[str, float]]:
    cfg = load_agent_config().get("pricing", {})
    if not isinstance(cfg, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for model, rates in cfg.items():
        if not isinstance(rates, dict):
            continue
        out[str(model)] = {
            "input_per_mtok_usd": float(rates.get("input_per_mtok_usd", 0.0)),
            "output_per_mtok_usd": float(rates.get("output_per_mtok_usd", 0.0)),
        }
    return out


def estimate_llm_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = load_pricing()
    rates = pricing.get(model)
    if rates is None:
        for key, val in pricing.items():
            if model.startswith(key.split("-")[0]):
                rates = val
                break
    if rates is None:
        rates = {"input_per_mtok_usd": 0.0, "output_per_mtok_usd": 0.0}
    cost = (
        (input_tokens / 1_000_000) * rates["input_per_mtok_usd"]
        + (output_tokens / 1_000_000) * rates["output_per_mtok_usd"]
    )
    return round(cost, 6)


def usage_from_anthropic(response: object, model: str) -> LlmUsageRecord:
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cost = estimate_llm_cost_usd(model, input_tokens, output_tokens)
    return LlmUsageRecord(model=model, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)


def usage_from_gemini(response: object, model: str) -> LlmUsageRecord:
    meta = getattr(response, "usage_metadata", None)
    input_tokens = int(getattr(meta, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(meta, "candidates_token_count", 0) or 0)
    if input_tokens == 0 and output_tokens == 0:
        input_tokens = int(getattr(meta, "total_token_count", 0) or 0)
    cost = estimate_llm_cost_usd(model, input_tokens, output_tokens)
    return LlmUsageRecord(model=model, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)


def merge_usage_records(records: list[LlmUsageRecord]) -> LlmUsageRecord:
    if not records:
        return LlmUsageRecord(model="", input_tokens=0, output_tokens=0, cost_usd=0.0)
    model = records[0].model
    input_tokens = sum(r.input_tokens for r in records)
    output_tokens = sum(r.output_tokens for r in records)
    cost_usd = round(sum(r.cost_usd for r in records), 6)
    return LlmUsageRecord(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
