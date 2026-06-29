from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

from agent.core.config import load_agent_config

_run_usage_accumulator: contextvars.ContextVar["_RunUsageAccumulator | None"] = contextvars.ContextVar(
    "run_usage_accumulator",
    default=None,
)


@dataclass
class LlmUsageRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class _RunUsageAccumulator:
    records: list[LlmUsageRecord] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(r.cost_usd for r in self.records), 6)

    @property
    def primary_model(self) -> str | None:
        if not self.records:
            return None
        by_cost = max(self.records, key=lambda r: r.cost_usd)
        return by_cost.model


def start_run_usage_tracking() -> None:
    _run_usage_accumulator.set(_RunUsageAccumulator())


def clear_run_usage_tracking() -> None:
    _run_usage_accumulator.set(None)


def get_run_usage_accumulator() -> _RunUsageAccumulator | None:
    return _run_usage_accumulator.get()


def record_llm_usage(record: LlmUsageRecord) -> None:
    acc = _run_usage_accumulator.get()
    if acc is not None:
        acc.records.append(record)


def load_pricing() -> dict[str, dict[str, float]]:
    cfg = load_agent_config().get("pricing", {})
    if not isinstance(cfg, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for model, rates in cfg.items():
        if model == "gemini-video-per-minute-usd":
            continue
        if not isinstance(rates, dict):
            continue
        out[str(model)] = {
            "input_per_mtok_usd": float(rates.get("input_per_mtok_usd", 0.0)),
            "output_per_mtok_usd": float(rates.get("output_per_mtok_usd", 0.0)),
        }
    return out


def gemini_video_per_minute_usd() -> float:
    cfg = load_agent_config().get("pricing", {})
    if isinstance(cfg, dict):
        return float(cfg.get("gemini-video-per-minute-usd", 0.05))
    return 0.05


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


def estimate_gemini_video_cost_usd(duration_s: float, model: str = "gemini-2.5-pro") -> float:
    _ = model
    minutes = max(duration_s, 0.0) / 60.0
    return round(minutes * gemini_video_per_minute_usd(), 6)


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
