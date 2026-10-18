"""Génération RÉELLE d'un Short par Claude Code CLI (opt-in, ~10-15 min, consomme du quota).

    CUTEVIDEO_LIVE_TESTS=1 pytest tests/test_studio_live.py -s

Utilise le vrai `claude` (votre propre connexion `claude`, aucune clé payante transmise), les vraies
banques d'images et la vraie synthèse vocale. Vérifie les invariants d'une
vidéo publiable, pas son contenu créatif.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

from studio.contracts import PublishMetadata, Brief, Critique, Scenario, StudioResult, Thumbnail, load_contract
from studio.launcher import LaunchConfig, prepare_run_dir, run_claude
from studio.media import probe_media

pytestmark = pytest.mark.skipif(
    os.getenv("CUTEVIDEO_LIVE_TESTS") != "1",
    reason="test réel (Claude + API externes) : CUTEVIDEO_LIVE_TESTS=1 pour l'activer",
)

TARGET_S = 20


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def live_run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if shutil.which(os.getenv("CLAUDE_BIN", "claude")) is None:
        pytest.skip("CLI claude introuvable")
    run_dir = prepare_run_dir(
        tmp_path_factory.mktemp("studio_live") / "run",
        # Une itération et seuil 0 : on teste la chaîne complète au moindre coût.
        Brief(theme="Pourquoi le ciel est bleu", target_duration_s=TARGET_S, max_iterations=1, min_score=0),
    )
    roles: list[str] = []

    async def on_event(kind: str, data: dict) -> None:
        if kind == "agent_start":
            roles.append(data["role"])
            print(f"▶ {data['role']}", flush=True)

    session = _run(run_claude(run_dir, cfg=LaunchConfig(timeout_s=2400), on_event=on_event))
    print(f"Run dir : {run_dir}")
    return {"run_dir": run_dir, "roles": roles, "session": session}


def test_all_roles_ran(live_run: dict) -> None:
    assert live_run["session"]["is_error"] is False
    roles = live_run["roles"]
    expected = ["scenariste", "voix", "monteur", "critique", "miniaturiste"]
    assert set(expected) <= set(roles), roles
    # La miniature est faite une seule fois, après la boucle.
    assert roles.count("miniaturiste") == 1 and roles[-1] == "miniaturiste", roles
    # Le producteur peut refaire une étape (durée hors tolérance…), mais l'ordre du pipeline tient.
    first_seen = sorted(expected, key=roles.index)
    assert first_seen == expected, roles


def test_result_and_contracts(live_run: dict) -> None:
    run_dir: Path = live_run["run_dir"]
    result = load_contract(run_dir / "result.json", StudioResult)
    assert result.status in {"approved", "max_iterations"}
    assert result.final_video
    scenario = load_contract(run_dir / "scenario.json", Scenario)
    assert scenario.title and scenario.beats
    assert load_contract(run_dir / "publish.json", PublishMetadata).title  # fiche de publication du miniaturiste
    critique = load_contract(run_dir / "critique_1.json", Critique)
    assert 0 <= critique.score <= 100


def test_final_video_is_publishable(live_run: dict) -> None:
    run_dir: Path = live_run["run_dir"]
    result = load_contract(run_dir / "result.json", StudioResult)
    final = run_dir / str(result.final_video)
    info = _run(probe_media(final))
    assert (info["width"], info["height"]) == (1080, 1920)
    assert info["has_audio"]
    assert TARGET_S * 0.6 <= info["duration_s"] <= TARGET_S * 1.6
    summary = json.loads(final.with_suffix(".render.json").read_text(encoding="utf-8"))
    assert summary["subtitles"] is True
    assert summary["credits"], "chaque média doit avoir ses crédits (banques libres)"
    assert all(c.get("license") for c in summary["credits"])


def test_thumbnails_exist(live_run: dict) -> None:
    run_dir: Path = live_run["run_dir"]
    thumb = load_contract(run_dir / "thumbnail.json", Thumbnail)
    info = _run(probe_media(run_dir / thumb.vertical))
    assert (info["width"], info["height"]) == (1080, 1920)
