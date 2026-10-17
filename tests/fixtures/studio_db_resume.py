"""Reprise après redémarrage du worker, lancée en sous-processus par `tests/test_studio_resume.py`.

Infra de TEST jetable (DATABASE_URL / REDIS_URL) et faux CLI (`FAKE_CLAUDE_HANG_IN`, `FAKE_CLAUDE_LIMIT_IN`).
Cas : reprise de la session (`--resume`), repli sur une nouvelle session quand la transcription a disparu,
abandon après trop d'interruptions sans progrès, puis limite d'usage de l'abonnement (pause, autre projet
du même compte mis en pause sans appeler Claude, plafond de pauses, reprise au reset, mode clé API inchangé).
Affiche un JSON de constats sur la dernière ligne.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from unittest.mock import patch

from tests.fixtures.studio_db_scenario import fake_delete, fake_persist


async def _setup(*, subscription: bool = False) -> tuple[uuid.UUID, uuid.UUID]:
    from sqlalchemy import select

    from agent.core.api_keys import encrypt_api_key
    from agent.core.database import AsyncSessionFactory, Channel, Project, SubscriptionPlan, User, UserApiKey

    async with AsyncSessionFactory() as session:
        plan = (await session.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.name))).scalars().first()
        # Abonnement Claude (mode CLI) : réservé aux admins (ADMIN_ONLY_PROVIDERS), prioritaire sur la clé API.
        user = User(google_sub=f"test-{uuid.uuid4()}", email=f"{uuid.uuid4()}@test.local", subscription_id=plan.id,
                    is_admin=subscription)
        session.add(user)
        await session.flush()
        session.add(UserApiKey(user_id=user.id, provider="anthropic", encrypted_key=encrypt_api_key("sk-ant-api-test")))
        if subscription:
            session.add(UserApiKey(user_id=user.id, provider="claude_subscription",
                                   encrypted_key=encrypt_api_key("sk-ant-oat01-test")))
        channel = Channel(
            user_id=user.id, slug=f"test-{uuid.uuid4().hex[:8]}", name="Test", theme_category="animaux",
            composio_user_id="test", niche_prompt="vulgarisation animale",
            config={"publishing": {"enabled_platforms": ["youtube"]}},
        )
        session.add(channel)
        await session.flush()
        project = Project(channel_id=channel.id, theme="Pourquoi les flamants roses sont roses",
                          target_duration_seconds=15, status="pending")
        session.add(project)
        await session.commit()
        return project.id, user.id


async def _runs(pid: uuid.UUID) -> list[list]:
    from sqlalchemy import select

    from agent.core.database import AgentRun, AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        rows = (await session.execute(
            select(AgentRun).where(AgentRun.project_id == pid).order_by(AgentRun.started_at)
        )).scalars().all()
        return [[r.agent_name, r.status, r.iteration] for r in rows]


async def _project(pid: uuid.UUID) -> dict:
    from agent.core.database import AsyncSessionFactory, Project

    async with AsyncSessionFactory() as session:
        project = await session.get(Project, pid)
        return {"status": project.status, "error": project.error_message,
                "session": (project.config or {}).get("claude_studio_session")}


async def _interrupt_during(pid: uuid.UUID, agent_name: str) -> None:
    """Lance la création, attend que `agent_name` tourne, puis simule l'arrêt du worker."""
    from sqlalchemy import select

    from agent.core import pipeline_cancel
    from agent.core.database import AgentRun, AsyncSessionFactory
    from agent.core.orchestrator import Orchestrator

    task = asyncio.create_task(Orchestrator().run_pipeline(pid))
    for _ in range(600):
        await asyncio.sleep(0.5)
        async with AsyncSessionFactory() as session:
            running = (await session.execute(select(AgentRun).where(
                AgentRun.project_id == pid, AgentRun.agent_name == agent_name, AgentRun.status == "running",
            ))).scalars().first()
        if running or task.done():
            break
    assert not task.done(), task.exception()
    pipeline_cancel.mark_worker_shutdown()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    pipeline_cancel._worker_shutdown = False  # le « worker suivant »


async def _resume_like_new_worker(pid: uuid.UUID) -> dict:
    """Ce que fait le worker suivant : réconciliation, file, puis création avec `resume`."""
    from agent.core.orchestrator import Orchestrator
    from agent.core.pipeline_queue import dequeue_next_eligible
    from agent.core.pipeline_reconcile import reconcile_orphan_running_projects

    reconciled = await reconcile_orphan_running_projects(worker_id="test")
    result = await dequeue_next_eligible()
    payload = result.payload or {}
    error = None
    try:
        await Orchestrator().run_pipeline(pid, already_claimed=True, resume=bool(payload.get("resume")))
    except Exception as exc:  # abandon attendu dans le 3e cas
        error = str(exc)
    return {"reconciled": reconciled, "payload_resume": payload.get("resume"), "error": error}


def _transcripts(user_id: uuid.UUID, pid: uuid.UUID) -> int:
    from studio.launcher import default_runs_dir

    projects = default_runs_dir() / ".claude-config" / str(user_id) / "projects"
    return len(list(projects.glob(f"*{pid}*/*.jsonl")))


async def main() -> dict:
    from agent.core.queue import queue
    from studio.launcher import default_runs_dir

    from agent.core.pipeline_queue import PIPELINE_ZQUEUE

    await queue.connect()
    await queue.client.delete(PIPELINE_ZQUEUE)  # infra jetable : file vide au départ
    facts: dict = {}
    # Garde-fou disque neutralisé : il dépend de la machine de test, pas de la reprise.
    with patch("agent.core.storage.persist_video_to_storage", fake_persist), \
         patch("agent.core.pipeline_reset.delete_s3_object", fake_delete), \
         patch("agent.core.pipeline_queue.is_disk_sufficient", lambda: True):
        # 1. Interruption en plein montage → reprise de la même session.
        pid, uid = await _setup()
        os.environ["FAKE_CLAUDE_HANG_IN"] = "monteur"
        await _interrupt_during(pid, "editor_agent")
        facts["interrupted"] = {**await _project(pid), "runs": await _runs(pid),
                                "transcripts": _transcripts(uid, pid),
                                "scenario_kept": (default_runs_dir() / str(pid) / "scenario.json").is_file()}
        os.environ.pop("FAKE_CLAUDE_HANG_IN")
        facts["resume"] = await _resume_like_new_worker(pid)
        facts["resumed"] = {**await _project(pid), "runs": await _runs(pid), "transcripts": _transcripts(uid, pid),
                            "resume_file": (default_runs_dir() / str(pid) / "resume.json").exists()}

        # 2. Transcription perdue → repli sur une nouvelle session qui reprend depuis le run dir.
        pid2, uid2 = await _setup()
        os.environ["FAKE_CLAUDE_HANG_IN"] = "critique"
        await _interrupt_during(pid2, "critic_agent")
        os.environ.pop("FAKE_CLAUDE_HANG_IN")
        facts["fallback_before"] = await _runs(pid2)
        shutil.rmtree(default_runs_dir() / ".claude-config" / str(uid2) / "projects")
        facts["fallback"] = {**await _resume_like_new_worker(pid2), **await _project(pid2), "runs": await _runs(pid2)}

        # 3. Trop d'interruptions sans progrès → abandon, plus de remise en file.
        pid3, _ = await _setup()
        os.environ["FAKE_CLAUDE_HANG_IN"] = "scenariste"
        await _interrupt_during(pid3, "scenario_agent")
        os.environ.pop("FAKE_CLAUDE_HANG_IN")
        from sqlalchemy import update

        from agent.core.database import AsyncSessionFactory, Project

        async with AsyncSessionFactory() as session:
            project = await session.get(Project, pid3)
            state = {**project.config["claude_studio_session"], "resumes": 3, "progress": 0}
            await session.execute(update(Project).where(Project.id == pid3).values(
                config={**project.config, "claude_studio_session": state}))
            await session.commit()
        facts["give_up"] = {**await _resume_like_new_worker(pid3), **await _project(pid3)}
        from agent.core.pipeline_reconcile import reconcile_orphan_running_projects

        facts["give_up"]["reconciled_after"] = await reconcile_orphan_running_projects(worker_id="test")

        facts["limit"] = await _usage_limit_cases()
    return facts


async def _sibling_project(pid: uuid.UUID, *, limit_pauses: int | None = None) -> uuid.UUID:
    """Autre projet sur la même chaîne (même compte Claude)."""
    from agent.core.database import AsyncSessionFactory, Project

    async with AsyncSessionFactory() as session:
        source = await session.get(Project, pid)
        config = {"claude_studio_session": {"limit_pauses": limit_pauses}} if limit_pauses is not None else {}
        project = Project(channel_id=source.channel_id, theme=source.theme, target_duration_seconds=15,
                          status="pending", config=config)
        session.add(project)
        await session.commit()
        return project.id


async def _usage_limit_cases() -> dict:
    from sqlalchemy import update

    from agent.core.database import AsyncSessionFactory, Project
    from agent.core.orchestrator import Orchestrator
    from agent.core.pipeline_queue import dequeue_next_eligible
    from agent.core.pipeline_reconcile import resume_paused_projects
    from agent.core.queue import queue
    from agent.core.studio_resume import get_user_limit
    from studio.launcher import default_runs_dir

    facts: dict = {}
    # Limite pendant le monteur, mode abonnement → pause, session et run dir gardés.
    pid, uid = await _setup(subscription=True)
    os.environ["FAKE_CLAUDE_LIMIT_IN"] = "monteur"
    await Orchestrator().run_pipeline(pid)
    facts["paused"] = {**await _project(pid), "runs": await _runs(pid), "transcripts": _transcripts(uid, pid),
                       "user_limit": await get_user_limit(uid) is not None}
    # Même compte, limite connue : pause sans lancer Claude (ni run dir ni étape).
    sibling = await _sibling_project(pid)
    await Orchestrator().run_pipeline(sibling)
    facts["sibling"] = {**await _project(sibling), "runs": await _runs(sibling),
                        "run_dir": (default_runs_dir() / str(sibling)).exists()}
    # Plafond de pauses atteint → abandon.
    capped = await _sibling_project(pid, limit_pauses=6)
    error = None
    try:
        await Orchestrator().run_pipeline(capped)
    except Exception as exc:
        error = str(exc)
    facts["capped"] = {**await _project(capped), "raised": error}
    # Reset passé (horloge avancée) → le worker remet en file et la création reprend.
    async with AsyncSessionFactory() as session:
        project = await session.get(Project, pid)
        state = {**project.config["claude_studio_session"], "paused_until": "2000-01-01T00:00:00+00:00"}
        await session.execute(update(Project).where(Project.id == pid).values(
            config={**project.config, "claude_studio_session": state}))
        await session.commit()
    await queue.client.delete(f"claude_limit:{uid}")
    async with AsyncSessionFactory() as session:  # le projet frère reste en pause : on le sort du jeu
        await session.execute(update(Project).where(Project.id == sibling).values(status="stopped"))
        await session.commit()
    facts["requeued"] = await resume_paused_projects()
    payload = (await dequeue_next_eligible()).payload or {}
    await Orchestrator().run_pipeline(pid, already_claimed=True, resume=bool(payload.get("resume")))
    facts["resumed"] = {**await _project(pid), "runs": await _runs(pid), "payload_resume": payload.get("resume")}
    os.environ.pop("FAKE_CLAUDE_LIMIT_IN")
    # Mode clé API : une limite reste un échec normal.
    api_pid, _ = await _setup()
    os.environ["FAKE_CLAUDE_LIMIT_IN"] = "monteur"
    error = None
    try:
        await Orchestrator().run_pipeline(api_pid)
    except Exception as exc:
        error = str(exc)
    os.environ.pop("FAKE_CLAUDE_LIMIT_IN")
    facts["api_key"] = {**await _project(api_pid), "raised": error}
    return facts


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, default=str))
