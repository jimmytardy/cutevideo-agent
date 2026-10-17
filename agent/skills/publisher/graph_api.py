"""Version de la Graph API Meta (Instagram) : une seule constante, surchargeable par l'environnement.

Module feuille (aucune dépendance) : importé par le publisher Instagram et par la validation des clés
(agent/core) sans tirer aiohttp ni créer de cycle.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# Meta publie une version par trimestre, chacune supportée ~2 ans : relever GRAPH_API_DEFAULT_VERSION quand la
# version courante approche de sa fin de support (https://developers.facebook.com/docs/graph-api/changelog).
GRAPH_API_DEFAULT_VERSION = "v26.0"
_VERSION_RE = re.compile(r"^v\d+\.\d+$")


def graph_api_version() -> str:
    """`INSTAGRAM_GRAPH_API_VERSION` si elle a la forme `vNN.N`, sinon le défaut (valeur invalide signalée)."""
    raw = os.getenv("INSTAGRAM_GRAPH_API_VERSION", "").strip()
    if not raw:
        return GRAPH_API_DEFAULT_VERSION
    if not _VERSION_RE.match(raw):
        logger.warning("INSTAGRAM_GRAPH_API_VERSION=%r ignorée (forme attendue vNN.N) : %s", raw, GRAPH_API_DEFAULT_VERSION)
        return GRAPH_API_DEFAULT_VERSION
    return raw


def graph_api_url(path: str) -> str:
    """URL Graph API versionnée : `graph_api_url("me")` → `https://graph.facebook.com/v26.0/me`."""
    return f"https://graph.facebook.com/{graph_api_version()}/{path.lstrip('/')}"
