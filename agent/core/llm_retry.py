"""Retry centralisé pour les appels LLM (Gemini, Anthropic, …).

Les fournisseurs LLM renvoient régulièrement des erreurs *transitoires* — surcharge
serveur (503 UNAVAILABLE / overloaded), throttling (429 RESOURCE_EXHAUSTED / rate
limit) ou erreur interne (500). Elles ne signalent pas un bug applicatif : un
nouvel essai après un court backoff réussit presque toujours.

Ce module fournit un détecteur unique (`is_transient_llm_error`) et deux
enrobages de retry (`retry_transient_sync` / `retry_transient_async`) à utiliser
sur chaque appel réseau vers un LLM, afin que tout le pipeline absorbe ces aléas
au lieu d'échouer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# Backoff exponentiel : essais à t=0, +5s, +10s par défaut (3 tentatives).
MAX_TRANSIENT_RETRIES = 3
TRANSIENT_BACKOFF_BASE_S = 5.0

# Codes HTTP transitoires exposés par certains SDK (Anthropic : exc.status_code).
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504, 529})

# Marqueurs présents dans le texte de l'exception (Gemini renvoie p.ex.
# "503 UNAVAILABLE" ou "429 RESOURCE_EXHAUSTED").
_TRANSIENT_TOKENS = (
    "503",
    "429",
    "500",
    "502",
    "504",
    "529",
    "unavailable",
    "overloaded",
    "resource_exhausted",
    "resource exhausted",
    "rate limit",
    "rate_limit",
    "too many requests",
    "internal error",
    "internal_error",
    "service unavailable",
    "try again later",
    "temporarily unavailable",
)


def is_transient_llm_error(exc: BaseException) -> bool:
    """True si l'erreur est transitoire (surcharge/throttling/erreur interne)."""
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and status in _TRANSIENT_STATUS_CODES:
        return True
    msg = str(exc).lower()
    return any(token in msg for token in _TRANSIENT_TOKENS)


def _backoff_delay(attempt: int) -> float:
    return TRANSIENT_BACKOFF_BASE_S * (2**attempt)


def retry_transient_sync(
    fn: Callable[[], _T],
    *,
    label: str = "llm",
    max_retries: int = MAX_TRANSIENT_RETRIES,
) -> _T:
    """Exécute `fn` en réessayant sur erreur LLM transitoire (version synchrone)."""
    last: BaseException | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — on réémet si non transitoire
            if not is_transient_llm_error(exc):
                raise
            last = exc
            if attempt < max_retries - 1:
                delay = _backoff_delay(attempt)
                logger.warning(
                    "Appel LLM transitoirement indisponible (%s) : %s — "
                    "retry %d/%d dans %ss",
                    label,
                    exc,
                    attempt + 1,
                    max_retries - 1,
                    delay,
                )
                time.sleep(delay)
    assert last is not None
    raise last


async def retry_transient_async(
    fn: Callable[[], Awaitable[_T]],
    *,
    label: str = "llm",
    max_retries: int = MAX_TRANSIENT_RETRIES,
) -> _T:
    """Exécute `fn` en réessayant sur erreur LLM transitoire (version asynchrone)."""
    last: BaseException | None = None
    for attempt in range(max_retries):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 — on réémet si non transitoire
            if not is_transient_llm_error(exc):
                raise
            last = exc
            if attempt < max_retries - 1:
                delay = _backoff_delay(attempt)
                logger.warning(
                    "Appel LLM transitoirement indisponible (%s) : %s — "
                    "retry %d/%d dans %ss",
                    label,
                    exc,
                    attempt + 1,
                    max_retries - 1,
                    delay,
                )
                await asyncio.sleep(delay)
    assert last is not None
    raise last
