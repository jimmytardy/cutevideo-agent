"""Génération complète à travers l'application : Orchestrator → ClaudeStudioRunner → DB.

Même faux CLI Claude que `test_studio_generation.py`, mais via le vrai
orchestrateur, Postgres et Redis. Nécessite une infra de TEST jetable (jamais la
base de dev) ; le test est ignoré sinon :

    docker run -d --rm --name cutevideo-pg-test -e POSTGRES_USER=cv -e POSTGRES_PASSWORD=cv \\
        -e POSTGRES_DB=cv -p 127.0.0.1:5440:5432 postgres:16-alpine
    docker run -d --rm --name cutevideo-redis-test -p 127.0.0.1:6390:6379 redis:7-alpine
    CUTEVIDEO_TEST_DATABASE_URL=postgresql+asyncpg://cv:cv@127.0.0.1:5440/cv \\
    CUTEVIDEO_TEST_REDIS_URL=redis://127.0.0.1:6390 pytest tests/test_studio_pipeline_db.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.studio_fakes import install_fake_claude

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_URL = os.getenv("CUTEVIDEO_TEST_DATABASE_URL")
REDIS_URL = os.getenv("CUTEVIDEO_TEST_REDIS_URL")

pytestmark = pytest.mark.skipif(
    not (DB_URL and REDIS_URL),
    reason="CUTEVIDEO_TEST_DATABASE_URL et CUTEVIDEO_TEST_REDIS_URL requis (infra de test jetable)",
)


@pytest.fixture(scope="module")
def facts(tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("studio_db")
    env = {
        **os.environ,
        "DATABASE_URL": DB_URL or "",
        "REDIS_URL": REDIS_URL or "",
        "CLAUDE_BIN": str(install_fake_claude(root / "bin")),
        "STUDIO_RUNS_DIR": str(root / "runs"),
        "FFMPEG_PRESET": "ultrafast",
        "PYTHONPATH": str(REPO_ROOT),
    }
    # Exécutable et sans PYTHONPATH : le dossier alembic/ du repo masquerait le paquet.
    migrate = subprocess.run(
        [str(Path(sys.executable).with_name("alembic")), "upgrade", "head"],
        cwd=REPO_ROOT, env={k: v for k, v in env.items() if k != "PYTHONPATH"},
        capture_output=True, text=True,
    )
    assert migrate.returncode == 0, migrate.stderr[-3000:]
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tests" / "fixtures" / "studio_db_scenario.py")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=1200,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_project_is_approved_and_titled(facts: dict) -> None:
    assert facts["status"] == "approved"
    assert facts["title"] == "Les flamants naissent gris"


def test_videos_are_persisted_once_per_platform(facts: dict) -> None:
    # Deux créations successives : la relance a nettoyé la première (aucun doublon).
    assert facts["video_types"] == ["short_master", "short_tiktok", "short_youtube"]
    assert facts["platform_videos_stored"]
    assert facts["master_duration"] == pytest.approx(3.0, abs=0.25)
    assert facts["s3_deleted_on_restart"] == 2
    assert facts["preview_type"] in {"short_master", "short_tiktok", "short_youtube"}


def test_critic_loop_and_steps_are_recorded(facts: dict) -> None:
    assert facts["critiques"] == [[1, 70, "iterate"], [2, 86, "approve"]]
    assert facts["scenarios"] == 1
    steps = {(name, iteration) for name, status, iteration in facts["runs"] if status == "success"}
    assert {("scenario_agent", 1), ("narrator_agent", 1), ("editor_agent", 1), ("thumbnail_agent", 1),
            ("critic_agent", 1), ("editor_agent", 2), ("critic_agent", 2)} <= steps
    assert all(status == "success" for _, status, _ in facts["runs"])
    assert facts["progress"]["2"]["editor_agent"] == 100


def test_publication_metadata_thumbnail_and_credits(facts: dict) -> None:
    meta = facts["metadata"]
    assert meta["title"] == "Les flamants naissent gris"
    assert meta["tags"] == ["shorts", "animaux"]
    assert "Crédits :" in meta["description"] and "via Pexels" in meta["description"]
    assert facts["thumbnail"]["primary"] is True
    assert facts["thumbnail_exists"]
    studio = facts["studio"]
    assert studio["status"] == "approved"
    assert studio["scores"] == [70, 86]
    assert len(studio["credits"]) == 3


def test_project_deletion_cleans_everything(facts: dict) -> None:
    assert facts["videos_after_delete"] == 0
    assert facts["dirs_after_delete"] == [False, False]
