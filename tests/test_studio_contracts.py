from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.contracts import ContractError, Critique, Scenario, Timeline, load_contract


def _clip(media: str, start: float, end: float) -> dict:
    return {"media": media, "start": start, "end": end}


def test_timeline_accepts_contiguous_clips() -> None:
    timeline = Timeline(clips=[_clip("a.jpg", 0, 2.5), _clip("b.mp4", 2.5, 6.0)])
    assert timeline.duration == 6.0


def test_timeline_rejects_gap_between_clips() -> None:
    with pytest.raises(ValueError, match="trou ou chevauchement"):
        Timeline(clips=[_clip("a.jpg", 0, 2.5), _clip("b.mp4", 3.0, 6.0)])


def test_timeline_must_start_at_zero() -> None:
    with pytest.raises(ValueError, match="commencer à 0"):
        Timeline(clips=[_clip("a.jpg", 1.0, 2.5)])


def test_clip_end_must_follow_start() -> None:
    with pytest.raises(ValueError):
        Timeline(clips=[_clip("a.jpg", 0, 0)])


def test_critique_iterate_requires_changes() -> None:
    base = {"iteration": 1, "video": "renders/v1.mp4", "score": 60}
    with pytest.raises(ValueError, match="changes"):
        Critique(**base, decision="iterate")
    critique = Critique(
        **base,
        decision="iterate",
        changes=[{"role": "monteur", "instruction": "remplacer le plan 2"}],
    )
    assert critique.changes[0].role == "monteur"


def test_scenario_narration_joins_beats() -> None:
    scenario = Scenario(
        title="t",
        hook="Un.",
        beats=[{"text": "Un."}, {"text": " Deux. "}],
        publish={"title": "T"},
    )
    assert scenario.narration == "Un. Deux."


def test_load_contract_reports_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "timeline.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(ContractError, match="JSON valide"):
        load_contract(path, Timeline)
    path.write_text(json.dumps({"clips": []}), encoding="utf-8")
    with pytest.raises(ContractError, match="invalide"):
        load_contract(path, Timeline)
    with pytest.raises(ContractError, match="introuvable"):
        load_contract(tmp_path / "absent.json", Timeline)
