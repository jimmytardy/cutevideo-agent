from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from agent.core.config import load_agent_config, settings
from agent.core.database import AsyncSessionFactory, Scenario
from agent.skills.media.ai_image_result import MediaGap

logger = logging.getLogger(__name__)

ADAPT_SYSTEM = """Tu adaptes un scénario vidéo lorsque certaines images IA n'ont pas pu être générées.

Pour chaque segment concerné :
- Réécris narration_text pour ne plus exiger un visuel précis impossible à produire
- Renforce on_screen_text pour compenser l'absence d'image
- Ajoute "visual_optional": true
- Conserve order, duration_s, delivery_style et les autres champs inchangés sauf si nécessaire

Retourne UNIQUEMENT du JSON valide avec le scénario complet."""

ADAPT_PROMPT = """Sujet : {theme}

Segments sans visuel disponible (génération IA impossible) :
{gaps_text}

SCÉNARIO ACTUEL :
{scenario_json}

Adapte uniquement les segments listés. Copie les autres segments à l'identique.

Retourne :
{{
  "segments": [ ... tous les segments ... ],
  "total_duration_s": {total_duration_s}
}}"""


async def adapt_scenario_for_media_gaps(
    scenario: Scenario,
    gaps: list[MediaGap],
    *,
    theme: str,
) -> tuple[Scenario, list[int]]:
    """Réécrit le scénario pour les segments sans image IA possible."""
    if not gaps:
        return scenario, []

    segments = list(scenario.segments or [])
    gap_orders = {g.segment_order for g in gaps}
    gaps_text = "\n".join(
        f"- Segment {g.segment_order} : {g.reason} ({g.attempts} tentatives) — prompt : {g.prompt[:120]}"
        for g in gaps
    )

    prompt = ADAPT_PROMPT.format(
        theme=theme,
        gaps_text=gaps_text,
        scenario_json=json.dumps({"segments": segments}, ensure_ascii=False, indent=2),
        total_duration_s=scenario.total_duration_s or 0,
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    msg = await client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        system=ADAPT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    data: dict[str, Any] = json.loads(raw)
    new_segments = data.get("segments", segments)

    for seg in new_segments:
        order = seg.get("order", 0)
        if order in gap_orders:
            seg["visual_optional"] = True

    async with AsyncSessionFactory() as session:
        db_scenario = await session.get(Scenario, scenario.id)
        if db_scenario is None:
            return scenario, []
        db_scenario.segments = new_segments
        if data.get("total_duration_s") is not None:
            db_scenario.total_duration_s = int(data["total_duration_s"])
        await session.commit()
        await session.refresh(db_scenario)

    adapted_orders = sorted(gap_orders)
    logger.info(
        "Scénario adapté pour %d gap(s) média : segments %s",
        len(adapted_orders),
        adapted_orders,
    )
    return db_scenario, adapted_orders


def ai_fallback_attempt_config() -> tuple[str, int, int]:
    cfg = load_agent_config().get("media_sources", {}).get("ai_fallback", {})
    dev_plan = str(cfg.get("dev_plan", "flux_2_dev"))
    dev_attempts = int(cfg.get("dev_validation_attempts", 3))
    paid_attempts = int(cfg.get("paid_validation_attempts", 3))
    return dev_plan, dev_attempts, paid_attempts
