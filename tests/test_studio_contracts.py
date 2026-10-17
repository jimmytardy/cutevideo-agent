from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.contracts import ContractError, Critique, Scenario, ScenarioCritique, Timeline, load_contract


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


def test_critique_cannot_target_thumbnail() -> None:
    # La miniature est faite après la boucle, hors critique.
    with pytest.raises(ValueError):
        Critique(iteration=1, video="renders/v1.mp4", score=60, decision="iterate",
                 changes=[{"role": "miniaturiste", "instruction": "texte plus gros"}])


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


def test_video_critique_refuses_scenariste() -> None:
    with pytest.raises(ValueError, match="scénario est déjà validé"):
        Critique(iteration=1, video="renders/v1.mp4", score=60, decision="iterate",
                 changes=[{"role": "scenariste", "instruction": "réécrire le hook"}])


def test_video_critique_voice_change_carries_lines() -> None:
    critique = Critique(iteration=1, video="renders/v1.mp4", score=70, decision="iterate",
                        changes=[{"role": "voix", "lines": [2, 5], "instruction": "ralentir"}])
    assert critique.changes[0].lines == [2, 5]


def test_scenario_critique_iterate_requires_changes_or_claims() -> None:
    with pytest.raises(ValueError):
        ScenarioCritique(iteration=1, score=70, decision="iterate")
    critique = ScenarioCritique(iteration=1, score=85, decision="iterate", unverified_claims=["« 1 m » : à vérifier"])
    assert critique.unverified_claims


def test_scenario_sources_optional() -> None:
    base = {"title": "t", "hook": "h", "beats": [{"text": "h"}], "publish": {"title": "t"}}
    assert Scenario.model_validate(base).sources == []
    sourced = Scenario.model_validate({**base, "sources": [{"claim": "fait", "url": "https://example.org"}]})
    assert sourced.sources[0].checked is True
