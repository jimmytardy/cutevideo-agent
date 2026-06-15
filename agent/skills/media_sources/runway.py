from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 10
_TIMEOUT_S = 300  # 5 min max


class RunwayCreditError(Exception):
    """Raised when Runway rejects the request due to insufficient credits (HTTP 402)."""


def _generate_sync(
    prompt: str,
    output_path: Path,
    api_key: str,
    model: str,
    duration: int,
    ratio: str,
) -> bool:
    """Blocking Runway API call — must be run via asyncio.to_thread."""
    try:
        import httpx
        from runwayml import RunwayML
        from runwayml import APIStatusError

        client = RunwayML(api_key=api_key)
        try:
            task = client.text_to_video.create(
                model=model,
                prompt_text=prompt,
                duration=duration,
                ratio=ratio,
            )
        except APIStatusError as api_err:
            if api_err.status_code == 402 or "credit" in str(api_err).lower() or "insufficient" in str(api_err).lower():
                raise RunwayCreditError(str(api_err)) from api_err
            raise
        logger.info("Runway task créée : %s (modèle=%s, %ds)", task.id, model, duration)

        deadline = time.time() + _TIMEOUT_S
        while task.status not in ("SUCCEEDED", "FAILED", "CANCELLED"):
            if time.time() > deadline:
                logger.warning("Runway timeout après %ds (task=%s)", _TIMEOUT_S, task.id)
                return False
            time.sleep(_POLL_INTERVAL_S)
            task = client.tasks.retrieve(task.id)

        if task.status != "SUCCEEDED" or not task.output:
            logger.warning("Runway task %s terminée : %s", task.id, task.status)
            return False

        video_url = task.output[0]
        resp = httpx.get(video_url, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        logger.info("Runway clip sauvegardé : %s (%d KB)", output_path, len(resp.content) // 1024)
        return True

    except Exception as exc:
        logger.warning("Runway génération échouée : %s", exc)
        return False


async def generate_video_clip(
    prompt: str,
    output_dir: Path,
    *,
    runway_cfg: "RunwayConfig",  # type: ignore[name-defined]
    channel_id: str,
    timezone: str = "Europe/Paris",
    api_key: str | None = None,
) -> dict | None:
    """Generate a short B-roll video clip via Runway, respecting the monthly budget cap."""
    from agent.core.runway_budget import add_monthly_runway_cost, check_runway_budget

    if not runway_cfg.enabled:
        return None
    if not api_key:
        logger.debug("Clé Runway absente, skip")
        return None

    cost_usd = runway_cfg.default_duration_s * runway_cfg.cost_per_second_usd

    within_budget = await check_runway_budget(
        channel_id, cost_usd, runway_cfg.monthly_budget_usd, timezone
    )
    if not within_budget:
        logger.info(
            "Budget Runway mensuel atteint pour la chaîne %s (budget=%.2f$)",
            channel_id,
            runway_cfg.monthly_budget_usd,
        )
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"runway_{uuid.uuid4().hex[:8]}.mp4"

    try:
        success = await asyncio.to_thread(
            _generate_sync,
            prompt=prompt,
            output_path=output_path,
            api_key=api_key,
            model=runway_cfg.model,
            duration=runway_cfg.default_duration_s,
            ratio=runway_cfg.resolution,
        )
    except RunwayCreditError:
        from agent.core.runway_budget import set_runway_credit_error
        await set_runway_credit_error(channel_id)
        logger.warning(
            "Runway : crédits insuffisants pour la chaîne %s — flag posé, génération ignorée",
            channel_id,
        )
        return None

    if not success:
        return None

    await add_monthly_runway_cost(channel_id, cost_usd, timezone)

    return {
        "source": "runway",
        "url": str(output_path),
        "local_generated": str(output_path),
        "asset_type": "video",
        "license": "Runway AI Generated (proprietary)",
        "attribution": f"Clip généré par Runway {runway_cfg.model}",
        "title": prompt[:80],
        "cost_usd": cost_usd,
    }
