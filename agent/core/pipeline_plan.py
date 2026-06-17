"""Calcule la forme du pipeline (agents réellement concernés) selon le type de vidéo.

Source de vérité unique partagée avec l'orchestrateur : les règles ici doivent
rester alignées sur `Orchestrator.run_pipeline` / `_run_main_loop`. Le frontend
consomme ce plan pour n'afficher que les agents qui tournent vraiment pour le
format/production_mode/dérivation de la chaîne.
"""

from __future__ import annotations

from typing import Any

from agent.core.channel_config import ChannelRuntimeConfig

PREPARATION_BASE: list[str] = ["research_agent", "outline_agent", "scenario_agent"]
ITERATION_FIRST: list[str] = [
    "narrator_agent",
    "beat_planner_agent",
    "media_agent",
    "montage_planner_agent",
    "editor_agent",
    "subtitle_agent",
    "critic_agent",
]
ITERATION_REVISION: list[str] = ["revision_agent", *ITERATION_FIRST]

_SHORT_FORMATS = frozenset({"short_standalone", "short"})


def is_short_video(
    channel_config: ChannelRuntimeConfig,
    project_format: str | None,
    target_duration_seconds: int | None,
) -> bool:
    """Réplique `PipelineContext.is_short_project`."""
    if project_format in _SHORT_FORMATS:
        return True
    if channel_config.production_mode == "shorts_only":
        return True
    if target_duration_seconds is not None and target_duration_seconds <= 120:
        return True
    return False


def plan_post_production_agents(
    channel_config: ChannelRuntimeConfig,
    is_short: bool,
) -> list[str]:
    """Agents de post-production réellement exécutés.

    - short / shorts_only : export plateforme via short_editor (pas de clipper)
    - long_only : aucune dérivation short
    - mixed + native : short natif (pas de clipper)
    - mixed + crop/hybrid : clipper puis short_editor
    """
    if is_short:
        return ["short_editor_agent"]
    if channel_config.production_mode == "long_only":
        return []
    if channel_config.short_derivation.strategy == "native":
        return ["short_editor_agent"]
    return ["clipper_agent", "short_editor_agent"]


def plan_pipeline(
    channel_config: ChannelRuntimeConfig,
    *,
    project_format: str | None,
    target_duration_seconds: int | None,
    max_iterations_override: int | None = None,
) -> dict[str, Any]:
    is_short = is_short_video(channel_config, project_format, target_duration_seconds)

    preparation = list(PREPARATION_BASE)
    if not is_short:
        # hook_optimizer_agent est ignoré pour les shorts (cf. _run_pre_media_quality_agents)
        preparation.append("hook_optimizer_agent")

    base_max = max_iterations_override or channel_config.max_critic_iterations
    max_iterations = min(base_max, 2) if is_short else base_max

    return {
        "is_short": is_short,
        "preparation": preparation,
        "iteration_first": list(ITERATION_FIRST),
        "iteration_revision": list(ITERATION_REVISION),
        "post_production": plan_post_production_agents(channel_config, is_short),
        "max_iterations": max_iterations,
    }
