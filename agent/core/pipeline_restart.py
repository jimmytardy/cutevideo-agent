from __future__ import annotations

"""Helpers pour la reprise du pipeline après critique."""

_AGENT_ORDER = [
    "research_agent",
    "scenario_agent",
    "fact_checker_agent",
    "hook_optimizer_agent",
    "diagram_specialist_agent",
    "media_agent",
    "narrator_agent",
    "montage_planner_agent",
    "editor_agent",
    "subtitle_agent",
    "critic_agent",
]

_AGENT_LOOP_IDX: dict[str, int] = {
    "research_agent": 0,
    "scenario_agent": 1,
    "fact_checker_agent": 1,
    "hook_optimizer_agent": 1,
    "diagram_specialist_agent": 1,
    "media_agent": 2,
    "narrator_agent": 3,
    "montage_planner_agent": 4,
    "editor_agent": 5,
    "subtitle_agent": 6,
}

_REVISION_AGENTS = frozenset({
    "scenario_agent", "media_agent", "narrator_agent",
    "hook_optimizer_agent", "diagram_specialist_agent",
})

_VISUAL_CRITIC_KEYWORDS = frozenset({
    "statique", "static", "monotone", "monotonie", "plan long", "plans longs",
    "dynamisme", "visuel", "montage", "rythme",
})


def resolve_restart_step(
    requested_changes: list[dict] | None,
    start_from: str | None,
) -> str:
    """Retourne l'agent le plus amont mentionné dans les corrections."""
    agents_mentioned: list[str] = []
    if requested_changes:
        for change in requested_changes:
            agent = change.get("agent")
            if agent and agent in _AGENT_LOOP_IDX:
                agents_mentioned.append(str(agent))
    if start_from and start_from in _AGENT_LOOP_IDX:
        agents_mentioned.append(start_from)
    if not agents_mentioned:
        return start_from or "media_agent"
    return min(agents_mentioned, key=lambda a: _AGENT_LOOP_IDX.get(a, 99))


def needs_revision_agent(
    requested_changes: list[dict] | None,
    start_from: str | None,
) -> bool:
    """True si RevisionAgent doit tourner même quand start_from=editor_agent."""
    if not requested_changes:
        return False
    for change in requested_changes:
        if change.get("agent") in _REVISION_AGENTS:
            return True
    return start_from in _REVISION_AGENTS


def critic_rework_iteration(critic_iteration: int | None) -> int:
    """Itération pipeline où appliquer les corrections d'un rapport critique.

    Le critique termine l'itération N ; la révision reprend en itération N+1.
    """
    return (critic_iteration or 1) + 1


def should_skip_pool_reuse(critic_feedback: list[dict] | None) -> bool:
    if not critic_feedback:
        return False
    for change in critic_feedback:
        desc = (change.get("change_description") or "").lower()
        if any(kw in desc for kw in _VISUAL_CRITIC_KEYWORDS):
            return True
    return False
