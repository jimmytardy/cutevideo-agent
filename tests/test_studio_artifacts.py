"""Fichiers d'un run Claude Studio exposés au détail d'un projet (studio/artifacts.py)."""

from __future__ import annotations

import json

import pytest

from studio.artifacts import list_artifacts, resolve_artifact_file
from studio.contracts import ContractError


@pytest.fixture
def run_dir(tmp_path):
    (tmp_path / "renders").mkdir()
    (tmp_path / "thumbnails").mkdir()
    (tmp_path / "renders" / "v1.mp4").write_bytes(b"v1")
    (tmp_path / "renders" / "v2.mp4").write_bytes(b"v2")
    (tmp_path / "thumbnails" / "final_9x16.png").write_bytes(b"png")
    (tmp_path / "thumbnails" / "final_16x9.jpg").write_bytes(b"jpg")
    (tmp_path / "thumbnails" / "notes.txt").write_text("x")
    (tmp_path / "voice.wav").write_bytes(b"RIFF")
    (tmp_path / "voice.json").write_text(json.dumps({"duration_s": 41.2, "engine": "edge", "voice": "Remy"}))
    (tmp_path / "scenario.json").write_text(json.dumps({"title": "T", "hook": "H", "beats": [{"text": "a"}]}))
    (tmp_path / "critique_1.json").write_text(json.dumps({"iteration": 1, "score": 70, "scores": {"hook": 6}}))
    (tmp_path / "critique_2.json").write_text("{ invalide")
    (tmp_path / "brief.json").write_text("{}")
    return tmp_path


def test_list_artifacts_groups_by_iteration(run_dir):
    data = list_artifacts(run_dir)
    assert data["available"] is True
    assert data["scenario"]["title"] == "T"
    assert data["voice"]["path"] == "voice.wav" and data["voice"]["engine"] == "edge"
    it1, it2 = data["iterations"]["1"], data["iterations"]["2"]
    assert it1["render"]["path"] == "renders/v1.mp4"
    assert it1["thumbnails"] == []
    assert it1["critique"]["scores"] == {"hook": 6}
    # Miniature unique (après la boucle) : rattachée à la dernière itération.
    assert [t["path"] for t in it2["thumbnails"]] == ["thumbnails/final_16x9.jpg", "thumbnails/final_9x16.png"]
    assert it2["critique"] is None  # JSON invalide ignoré


def test_list_artifacts_missing_run_dir(tmp_path):
    data = list_artifacts(tmp_path / "absent")
    assert data["available"] is False and data["iterations"] == {}


def test_resolve_artifact_file_whitelist(run_dir):
    path, media_type = resolve_artifact_file(run_dir, "voice.wav")
    assert path.name == "voice.wav" and media_type == "audio/wav"
    assert resolve_artifact_file(run_dir, "renders/v2.mp4")[1] == "video/mp4"
    assert resolve_artifact_file(run_dir, "thumbnails/final_9x16.png")[1] == "image/png"
    for rel in ("brief.json", "scenario.json", "thumbnails/notes.txt", "../etc/passwd", "renders/../brief.json"):
        with pytest.raises(ContractError):
            resolve_artifact_file(run_dir, rel)
    with pytest.raises(FileNotFoundError):
        resolve_artifact_file(run_dir, "renders/v9.mp4")
