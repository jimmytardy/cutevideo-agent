"""Style visuel par chaîne : réglage, brief et contrôle de `scenario.visual_mode` par `validate`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.core.channel_config import resolve_channel_config
from studio.contracts import Brief, allowed_visual_modes

REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeChannel:
    theme_category = "animaux"
    brand_kit = None

    def __init__(self, studio: dict | None = None) -> None:
        self.config = {"studio": studio} if studio is not None else {}


@pytest.mark.parametrize(
    ("studio", "expected"),
    [(None, "animation"), ({"visual_style": "mixed"}, "mixed"), ({"visual_style": "realistic"}, "realistic"),
     ({"visual_style": "cinema"}, "animation")],
)
def test_channel_visual_style(studio: dict | None, expected: str) -> None:
    assert resolve_channel_config(_FakeChannel(studio)).studio_visual_style == expected  # type: ignore[arg-type]


def test_brief_defaults_to_animation() -> None:
    assert Brief(theme="x").visual_style == "animation"


def test_allowed_visual_modes() -> None:
    assert allowed_visual_modes("animation", "scripts") == ("animation", "mixed", "footage")
    assert allowed_visual_modes("mixed", "scripts") == ("mixed",)
    assert allowed_visual_modes("realistic", "templates") == ("footage", "mixed")
    assert allowed_visual_modes("mixed", "off") == ("footage",)  # sans animation, que des images réelles


def _validate(tmp_path: Path, visual_mode: str, style: str, animations: str = "scripts") -> dict:
    (tmp_path / "scenario.json").write_text(json.dumps({
        "title": "T", "hook": "H", "beats": [{"text": "Une phrase."}], "visual_mode": visual_mode,
        "publish": {"title": "T"},
    }), encoding="utf-8")
    env = {**os.environ, "STUDIO_RUN_DIR": str(tmp_path), "STUDIO_VISUAL_STYLE": style,
           "STUDIO_ANIMATIONS": animations, "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.run(
        [sys.executable, "-m", "studio.tools", "validate", "--kind", "scenario", "--path", "scenario.json"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )
    return json.loads(proc.stdout)


def test_validate_enforces_channel_visual_style(tmp_path: Path) -> None:
    assert _validate(tmp_path, "animation", "animation")["valid"] is True
    refused = _validate(tmp_path, "animation", "mixed")
    assert "interdit" in refused["error"] and "mixed" in refused["error"]
    assert _validate(tmp_path, "footage", "realistic")["valid"] is True
    assert "footage" in _validate(tmp_path, "mixed", "animation", animations="off")["error"]
