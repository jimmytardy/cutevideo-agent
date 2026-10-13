"""Helpers partagés par les tests de génération complète (faux CLI Claude)."""

from __future__ import annotations

import functools
import stat
import sys
from pathlib import Path

FAKE_CLAUDE = Path(__file__).resolve().parent / "fixtures" / "fake_claude.py"


def install_fake_claude(directory: Path) -> Path:
    """Exécutable `claude` qui lance le faux CLI avec l'interpréteur des tests."""
    directory.mkdir(parents=True, exist_ok=True)
    wrapper = directory / "claude"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE}" "$@"\n', encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return wrapper


@functools.lru_cache(maxsize=1)
def playwright_chromium_available() -> bool:
    """Chromium headless de Playwright installé (`playwright install --only-shell chromium`)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception:  # noqa: BLE001 — binaire absent ou dépendances système manquantes
        return False
    return True
