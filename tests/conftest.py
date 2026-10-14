from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _api_keys_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clé de chiffrement de test : les tests ne dépendent pas du .env de la machine."""
    from agent.core.config import settings

    monkeypatch.setattr(settings, "api_keys_encryption_key", "ab" * 32)
