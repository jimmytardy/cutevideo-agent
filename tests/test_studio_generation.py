"""Génération complète d'un Short, de bout en bout, sans appeler Claude.

Passe par le vrai lanceur (`prepare_run_dir` + `run_claude` : sous-processus,
environnement, permissions, parsing stream-json), les vrais outils
`python -m studio.tools` et le vrai rendu ffmpeg. Seul le CLI `claude` est
remplacé par `tests/fixtures/fake_claude.py`, qui joue le producteur de façon
déterministe (2 itérations : reprise demandée puis approbation).

Le pendant « vrai Claude » est `tests/test_studio_live.py` (opt-in).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest

from studio.contracts import PublishMetadata, Brief, Critique, Scenario, ScenarioCritique, StudioResult, Thumbnail, Timeline, load_contract
from studio.launcher import ROLES, WORKSPACE_TEMPLATE, LaunchConfig, prepare_run_dir, run_claude
from studio.media import probe_media
from studio.sandbox import scripts_supported
from studio.tools import build_parser
from tests.studio_fakes import install_fake_claude, playwright_chromium_available

# Le faux producteur ajoute des plans animés à l'itération 2 quand le bac à sable est disponible.
ANIMATIONS = "scripts" if playwright_chromium_available() and scripts_supported() else "off"


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Une seule génération pour tout le module (rendu ffmpeg ≈ 30 s)."""
    root = tmp_path_factory.mktemp("studio_generation")
    claude_bin = install_fake_claude(root / "bin")
    run_dir = prepare_run_dir(
        root / "run",
        Brief(theme="Pourquoi les flamants roses sont roses", target_duration_s=15, max_iterations=2,
              animations=ANIMATIONS),
    )
    events: list[tuple[str, dict]] = []

    async def on_event(kind: str, data: dict) -> None:
        events.append((kind, data))

    cfg = LaunchConfig(claude_bin=str(claude_bin), timeout_s=600)
    previous = os.environ.get("FFMPEG_PRESET")
    os.environ["FFMPEG_PRESET"] = "ultrafast"  # hérité par les outils lancés par le faux CLI
    try:
        result = asyncio.run(run_claude(run_dir, cfg=cfg, on_event=on_event))
    finally:
        if previous is None:
            os.environ.pop("FFMPEG_PRESET", None)
        else:
            os.environ["FFMPEG_PRESET"] = previous
    return {"run_dir": run_dir, "events": events, "result": result}


def test_session_succeeds(generated: dict) -> None:
    assert generated["result"]["is_error"] is False
    assert (generated["run_dir"] / "claude_stream.jsonl").stat().st_size > 0


def test_subagents_run_in_pipeline_order_with_iteration(generated: dict) -> None:
    starts = [d["role"] for kind, d in generated["events"] if kind == "agent_start"]
    # Boucle scénario (2 passes) avant la voix ; itération vidéo 2 : seul le monteur est cité (voix réutilisée) ;
    # la miniature est faite une fois, à la fin.
    assert starts == [
        "scenariste", "critique-scenario", "scenariste", "critique-scenario",
        "voix", "monteur", "critique", "monteur", "critique", "miniaturiste",
    ]
    ends = [d for kind, d in generated["events"] if kind == "agent_end"]
    assert len(ends) == len(starts)
    assert not any(d["is_error"] for d in ends)
    # Le rapport du sous-agent est débarrassé de l'en-tête/pied de Claude Code.
    assert ends[0]["output"] == "3 beats, 15 mots."


def test_tool_calls_are_attributed_to_subagents(generated: dict) -> None:
    tools = [d for kind, d in generated["events"] if kind == "tool"]
    rendered_by = {d["role"] for d in tools if "studio.tools render" in d["input"]["command"]}
    assert rendered_by == {"monteur"}
    assert all(d["input"]["command"].startswith("python -m studio.tools ") for d in tools)
    assert ("denied", {"role": "producteur", "name": "WebFetch"}) in generated["events"]


def test_all_contract_files_are_valid(generated: dict) -> None:
    run_dir: Path = generated["run_dir"]
    scenario = load_contract(run_dir / "scenario.json", Scenario)
    assert scenario.title and scenario.publish is None  # la fiche de publication n'est plus dans le scénario
    assert load_contract(run_dir / "publish.json", PublishMetadata).title == "Les flamants naissent gris"
    # Boucle scénario : la passe 1 signale un fait à vérifier, la passe 2 (sourcée) est approuvée.
    passes = [load_contract(run_dir / f"scenario_critique_{i}.json", ScenarioCritique) for i in (1, 2)]
    assert [c.decision for c in passes] == ["iterate", "approve"]
    assert passes[0].unverified_claims and scenario.sources
    assert load_contract(run_dir / "timeline.json", Timeline).duration == pytest.approx(3.0)
    critiques = [load_contract(run_dir / f"critique_{i}.json", Critique) for i in (1, 2)]
    assert [c.decision for c in critiques] == ["iterate", "approve"]
    result = load_contract(run_dir / "result.json", StudioResult)
    assert result.status == "approved"
    assert result.final_video == "renders/v2.mp4"


def test_final_video_is_a_vertical_short_with_audio(generated: dict) -> None:
    run_dir: Path = generated["run_dir"]
    final = run_dir / "renders" / "v2.mp4"
    info = asyncio.run(probe_media(final))
    assert (info["width"], info["height"]) == (1080, 1920)
    assert info["has_audio"]
    assert info["duration_s"] == pytest.approx(3.0, abs=0.25)
    summary = json.loads((run_dir / "renders" / "v2.render.json").read_text(encoding="utf-8"))
    assert summary["subtitles"] is True
    if ANIMATIONS == "scripts":
        # v2 : plan 2 = script jetable, plan 3 = modèle « counter » (crédits « original »).
        assert [c["media"] for c in summary["credits"]] == [
            "media/01_poussin.png", "media/anim_02_schema.mp4", "media/anim_03_chiffre.mp4",
        ]
        assert [c["license"] for c in summary["credits"][1:]] == ["original", "original"]
    else:
        assert [c["media"] for c in summary["credits"]] == [
            "media/01_poussin.png", "media/02_repas.mp4", "media/03_silhouette.png",
        ]
    # Les deux itérations ont été rendues et revues par la critique.
    assert (run_dir / "renders" / "v1.mp4").is_file()
    assert (run_dir / "review" / "v2" / "sheet.png").is_file()


def test_thumbnails_have_expected_formats(generated: dict) -> None:
    run_dir: Path = generated["run_dir"]
    thumb = load_contract(run_dir / "thumbnail.json", Thumbnail)
    sizes = {}
    for rel in (thumb.vertical, thumb.horizontal):
        info = asyncio.run(probe_media(run_dir / rel))
        sizes[rel] = (info["width"], info["height"])
    assert sizes == {"thumbnails/final_9x16.png": (1080, 1920), "thumbnails/final_16x9.png": (1280, 720)}


def test_workspace_only_references_existing_tools() -> None:
    """Les consignes des sous-agents ne doivent citer que des commandes qui existent."""
    commands = set(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
    texts = [WORKSPACE_TEMPLATE.joinpath("CLAUDE.md").read_text(encoding="utf-8")]
    texts += [p.read_text(encoding="utf-8") for p in (WORKSPACE_TEMPLATE / ".claude").rglob("*.md")]
    texts += [p.read_text(encoding="utf-8") for p in (WORKSPACE_TEMPLATE / "docs").rglob("*.md")]
    cited = set()
    for text in texts:
        cited |= set(re.findall(r"studio\.tools ([a-z-]+)", text))
        cited |= set(re.findall(r"^\| `([a-z-]+)[ `]", text, flags=re.M))
    assert cited, "aucune commande citée : regex à revoir"
    assert cited <= commands, f"commandes inconnues dans le workspace : {cited - commands}"
    for role in ROLES:
        assert (WORKSPACE_TEMPLATE / ".claude" / "agents" / f"{role}.md").is_file()
