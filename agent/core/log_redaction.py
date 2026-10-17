"""Configuration des logs des processus (API, worker) sans secrets dans les URLs.

httpx logge en INFO l'URL complète de chaque requête sortante, et le log d'accès d'uvicorn le chemin complet de
chaque requête entrante : un jeton passé en paramètre (`?access_token=` des lecteurs média du dashboard, Graph
API Instagram…) finirait en clair dans les logs. Un filtre masque la valeur des paramètres sensibles.
"""

from __future__ import annotations

import logging
import re

import httpx

_SENSITIVE_PARAM = re.compile(
    r"(?i)([?&](?:access_token|token|refresh_token|id_token|client_secret|api_key|apikey|key|sig|signature"
    r"|x-amz-signature|x-amz-credential|x-amz-security-token)=)[^&#\s\"']+"
)
REDACTED = "***"
# Loggers qui écrivent des URLs : requêtes sortantes (httpx) et log d'accès de l'API.
_URL_LOGGERS = ("httpx", "uvicorn.access")


def redact_url(text: str) -> str:
    """Masque la valeur des paramètres sensibles d'une URL ou d'une ligne qui en contient."""
    return _SENSITIVE_PARAM.sub(rf"\1{REDACTED}", text)


class RedactSecretsFilter(logging.Filter):
    """Réécrit message et arguments d'un enregistrement (httpx passe un `httpx.URL`, pas une chaîne)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_url(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_url(str(arg)) if isinstance(arg, str | httpx.URL) else arg
                for arg in record.args
            )
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """`basicConfig` des processus + filtre anti-secrets sur les loggers qui écrivent des URLs."""
    logging.basicConfig(level=level, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for name in _URL_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactSecretsFilter) for f in logger.filters):
            logger.addFilter(RedactSecretsFilter())
