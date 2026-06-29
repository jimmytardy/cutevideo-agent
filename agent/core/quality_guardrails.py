from __future__ import annotations

from agent.core.subscription import SubscriptionLimits, resolve_effective_max_critic_iterations


def resolve_effective_quality_iterations(
    *,
    project_config: dict,
    channel_quality_max: int,
    channel_critic_max: int,
    limits: SubscriptionLimits,
) -> int | None:
    """Plafond effectif d'itérations qualité (min garde-fou technique + abonnement).

    ``quality.max_iterations`` borne toujours le pipeline, même pour les admins
    sans plafond d'abonnement explicite.
    """
    quality_cap = int(
        project_config.get("quality_max_iterations")
        or channel_quality_max
    )
    critic_cap = resolve_effective_max_critic_iterations(
        project_config=project_config,
        channel_max=channel_critic_max,
        limits=limits,
    )
    if critic_cap is None:
        return quality_cap
    return min(quality_cap, critic_cap)
