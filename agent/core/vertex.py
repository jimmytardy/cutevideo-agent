"""Client Gemini servi par Vertex AI avec le compte de service GCP de l'utilisateur.

Partagé par le résolveur LLM des agents et par les outils Studio (voix, analyse vidéo) : Vertex
s'authentifie via le compte de service, pas via une clé AIza, et sert donc de repli quand la clé
Gemini Developer est absente ou refusée.
"""

from __future__ import annotations

import json
from typing import Any

from agent.core.config import settings

# Erreurs de la clé Gemini qui justifient un nouvel essai via Vertex : clé refusée ou invalide,
# accès interdit, quota épuisé.
KEY_REFUSED_CODES = frozenset({400, 401, 403, 429})


def gemini_key_refused(exc: BaseException) -> bool:
    """True si l'appel avec la clé Gemini a échoué pour une raison que Vertex peut contourner."""
    from google.genai import errors

    return isinstance(exc, errors.ClientError) and getattr(exc, "code", None) in KEY_REFUSED_CODES


def vertex_credentials(credentials_json: str | None) -> Any:
    """Credentials google-auth pour Vertex AI à partir du JSON du compte de service."""
    from google.oauth2 import service_account

    if not credentials_json:
        raise RuntimeError("compte de service GCP absent : ajoutez-le dans Compte → Clés API")
    return service_account.Credentials.from_service_account_info(
        json.loads(credentials_json), scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )


def vertex_project_id(credentials_json: str) -> str:
    try:
        project_id = str(json.loads(credentials_json).get("project_id") or "").strip()
    except (json.JSONDecodeError, AttributeError) as exc:
        raise RuntimeError("compte de service GCP illisible (JSON attendu)") from exc
    if not project_id:
        raise RuntimeError("compte de service GCP sans project_id")
    return project_id


def vertex_genai_client(
    credentials_json: str, location: str | None = None, *, project_id: str | None = None
) -> Any:
    """`genai.Client` Vertex : projet lu dans le JSON (sauf s'il est fourni), région sinon `settings.gcp_location`."""
    from google import genai

    return genai.Client(
        vertexai=True,
        project=project_id or vertex_project_id(credentials_json),
        location=(location or "").strip() or settings.gcp_location,
        credentials=vertex_credentials(credentials_json),
    )
