"""Garde anti-IDOR : toute route qui cible une ressource par id doit connaître l'utilisateur.

Le middleware n'exige qu'un JWT valide ; c'est la dépendance `get_current_user`
(puis `get_user_project` / `get_user_channel`) qui scope la ressource. Une route
paramétrée par id sans cette dépendance laisse lire les données d'un autre compte.
"""

from __future__ import annotations

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from api.deps import get_current_user
from api.main import app

_RESOURCE_PARAMS = ("{project_id}", "{channel_id}", "{publication_id}", "{video_id}")

# Redirections OAuth : l'utilisateur est identifié par le `state` signé, pas par le JWT.
_PUBLIC_CALLBACKS = {
    "/api/v1/channels/youtube/oauth/callback",
    "/api/v1/channels/{channel_id}/connect/tiktok/callback",
}


def _depends_on_current_user(dependant: Dependant) -> bool:
    return any(
        dep.call is get_current_user or _depends_on_current_user(dep)
        for dep in dependant.dependencies
    )


def _api_routes(routes=None) -> list[APIRoute]:
    """Routes à plat (FastAPI ≥ 0.140 enveloppe chaque `include_router`)."""
    flat: list[APIRoute] = []
    for route in app.routes if routes is None else routes:
        if isinstance(route, APIRoute):
            flat.append(route)
        elif hasattr(route, "original_router"):
            flat.extend(_api_routes(route.original_router.routes))
    return flat


def test_route_inventory_is_not_empty() -> None:
    assert len(_api_routes()) > 50


def test_resource_routes_require_current_user() -> None:
    unscoped = [
        f"{sorted(r.methods)} {r.path}"
        for r in _api_routes()
        if any(p in r.path for p in _RESOURCE_PARAMS)
        and r.path not in _PUBLIC_CALLBACKS
        and not _depends_on_current_user(r.dependant)
    ]
    assert unscoped == []


def test_global_run_triggers_are_admin_only() -> None:
    from api.deps import require_admin_user

    triggers = [
        r for r in _api_routes() if r.path in ("/api/v1/distribution/run", "/api/v1/content-planning/run")
    ]
    assert len(triggers) == 2
    for route in triggers:
        assert any(
            dep.call is require_admin_user for dep in route.dependant.dependencies
        ), route.path
