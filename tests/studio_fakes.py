"""Helpers partagés par les tests de génération complète (faux CLI Claude)."""

from __future__ import annotations

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
